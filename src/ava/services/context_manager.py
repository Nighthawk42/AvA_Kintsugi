# src/ava/services/context_manager.py
import ast
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass


@dataclass
class GenerationContext:
    """Comprehensive context for coordinated generation."""
    plan: Dict[str, Any]
    project_index: Dict[str, str]  # Maps symbol name to module_path string
    living_design_context: Dict[str, Any]
    dependency_order: List[str]
    generation_session: Dict[str, Any]  # Tracks files in current generation, their status, and their generated code
    rag_context: str
    relevance_scores: Dict[str, float]
    existing_files: Optional[Dict[str, str]]  # Files on disk *before* this session started


class ContextManager:
    """
    Manages comprehensive context for coordinated generation.
    """

    def __init__(self, service_manager):
        self.service_manager = service_manager

    async def build_generation_context(self, plan: Dict[str, Any], rag_context: str,
                                       existing_files: Optional[Dict[str, str]]) -> GenerationContext:
        project_indexer = self.service_manager.get_project_indexer_service()
        project_manager = self.service_manager.get_project_manager()

        initial_project_index = {}
        if project_manager and project_manager.active_project_path and existing_files:
            # Build index from existing files on disk at the start of the session
            for rel_path, content in existing_files.items():
                if rel_path.endswith(".py"):
                    module_path_str = rel_path.replace('.py', '').replace('/', '.')
                    symbols_in_file = project_indexer.get_symbols_from_content(content, module_path_str)
                    initial_project_index.update(symbols_in_file)

        # If it's a completely new project, the indexer might run on an empty dir
        # or we can rely on the rolling update. Let's ensure indexer is called if path exists.
        elif project_manager and project_manager.active_project_path:
            initial_project_index = project_indexer.build_index(project_manager.active_project_path)

        living_design_context = {}  # Placeholder for now

        generation_session = {}
        for file_info in plan.get("files", []):
            generation_session[file_info["filename"]] = {
                "purpose": file_info["purpose"],
                "status": "planned",
                "dependencies": self._extract_file_dependencies(file_info)
            }

        relevance_scores = self._calculate_relevance_scores(plan, initial_project_index, rag_context)

        return GenerationContext(
            plan=plan,
            project_index=initial_project_index,
            living_design_context=living_design_context,
            dependency_order=[],
            generation_session=generation_session,
            rag_context=rag_context,
            relevance_scores=relevance_scores,
            existing_files=existing_files or {}
        )

    async def update_session_context(self, context: GenerationContext,
                                     newly_generated_file: Dict[str, str]) -> GenerationContext:
        """
        Update the context with a newly generated file, including its symbols.
        This is the core of the "rolling context".
        MUST be awaited.
        """
        try:
            filename, code = list(newly_generated_file.items())[0]

            # Update the generation session log with the completed file
            if filename in context.generation_session:
                context.generation_session[filename]["status"] = "completed"
                context.generation_session[filename]["generated_code"] = code  # Store full code here

            # Update the project_index with symbols from the new code
            project_indexer = self.service_manager.get_project_indexer_service()
            updated_index = context.project_index.copy()

            if filename.endswith('.py'):
                module_path = filename.replace('.py', '').replace('/', '.')
                new_symbols = project_indexer.get_symbols_from_content(code, module_path)
                updated_index.update(new_symbols)
                print(
                    f"[ContextManager] Updated symbol index with {len(new_symbols)} symbols from new file: {filename}")

            # Return a NEW GenerationContext object with the updated index and session
            return GenerationContext(
                plan=context.plan,
                project_index=updated_index,
                living_design_context=context.living_design_context,
                dependency_order=context.dependency_order,
                generation_session=context.generation_session,  # This was already updated in-place
                rag_context=context.rag_context,
                relevance_scores=context.relevance_scores,
                existing_files=context.existing_files
            )

        except Exception as e:
            print(f"Error updating session context for {list(newly_generated_file.keys())[0]}: {e}")
            import traceback
            traceback.print_exc()
            return context  # Return original context on error

    # ... (rest of the methods _extract_file_dependencies, _calculate_relevance_scores, etc. remain unchanged)

    def _extract_file_dependencies(self, file_info: Dict[str, str]) -> List[str]:
        try:
            dependencies = []
            purpose = file_info.get("purpose", "").lower()
            filename = file_info.get("filename", "").lower()
            dependency_patterns = {
                "async": ["asyncio"], "path": ["pathlib"], "json": ["json"], "typing": ["typing"],
                "service": ["ava.core.event_bus"], "manager": ["pathlib", "typing"],
                "ui": ["tkinter", "PySide6"], "web": ["flask", "fastapi"],
                "database": ["sqlite3", "sqlalchemy"], "api": ["requests", "aiohttp"]
            }
            for keyword, deps in dependency_patterns.items():
                if keyword in purpose or keyword in filename:
                    dependencies.extend(deps)
            return list(set(dependencies))
        except Exception:
            return []

    def _calculate_relevance_scores(self, plan: Dict[str, Any],
                                    project_index: Dict[str, str],
                                    rag_context: str) -> Dict[str, float]:
        try:
            relevance_scores = {}
            plan_keywords = self._extract_keywords_from_plan(plan)
            for module_name, module_content in project_index.items():
                score = self._calculate_text_relevance(module_content, plan_keywords)
                relevance_scores[f"project_index:{module_name}"] = score
            if rag_context:
                rag_chunks = rag_context.split("--- Relevant Document Snippet")
                for i, chunk in enumerate(rag_chunks):
                    if chunk.strip():
                        score = self._calculate_text_relevance(chunk, plan_keywords)
                        relevance_scores[f"rag_chunk:{i}"] = score
            return relevance_scores
        except Exception:
            return {}

    def _extract_keywords_from_plan(self, plan: Dict[str, Any]) -> Set[str]:
        try:
            keywords = set()
            for file_info in plan.get("files", []):
                purpose = file_info.get("purpose", "")
                filename = file_info.get("filename", "")
                purpose_words = [word.strip().lower() for word in purpose.split()
                                 if len(word) > 3 and word.isalpha()]
                filename_words = [word.strip().lower() for word in filename.replace('.py', '').replace('_', ' ').split()
                                  if len(word) > 3 and word.isalpha()]
                keywords.update(purpose_words)
                keywords.update(filename_words)
            for dep in plan.get("dependencies", []):
                if isinstance(dep, str):
                    keywords.add(dep.lower())
            return keywords
        except Exception:
            return set()

    def _calculate_text_relevance(self, text: str, keywords: Set[str]) -> float:
        try:
            if not text or not keywords: return 0.0
            text_lower = text.lower()
            matches = sum(1 for keyword in keywords if keyword in text_lower)
            text_words = len(text.split())
            keyword_count = len(keywords)
            if text_words == 0 or keyword_count == 0: return 0.0
            base_score = matches / keyword_count
            length_weight = min(1.0, text_words / 100)
            return base_score * length_weight
        except Exception:
            return 0.0

    def get_filtered_context_for_file(self, filename: str, context: GenerationContext) -> Dict[str, Any]:
        # This method seems okay, its job is to select from already built context
        # The key is that the `context.project_index` and `context.generation_session` are up-to-date
        try:
            filtered_context = {}
            relevant_modules = self._get_relevant_modules(filename, context)  # Uses project_index
            filtered_context["relevant_modules"] = relevant_modules
            relevant_design = self._filter_design_context(filename, context.living_design_context)
            filtered_context["design_context"] = relevant_design
            relevant_rag = self._filter_rag_context(filename, context.rag_context)
            filtered_context["rag_context"] = relevant_rag
            dependencies = self._get_file_dependencies(filename, context)  # Uses plan
            filtered_context["dependencies"] = dependencies
            return filtered_context
        except Exception as e:
            print(f"Error filtering context for {filename}: {e}")
            return {}

    def _get_relevant_modules(self, filename: str, context: GenerationContext) -> Dict[str, str]:
        try:
            relevant_modules = {}
            file_stem = Path(filename).stem.lower()
            # Use context.project_index which should be up-to-date
            scored_modules = []
            for module_name, module_summary_or_code in context.project_index.items():  # This now contains module_path -> symbols_string
                # For relevance, we need content. The project_index now has symbol names.
                # We need the actual code from generation_session for files generated *in this session*
                # or from existing_files for files that were on disk.

                module_content_for_relevance = ""
                # Check if this module was generated in the current session
                # The project_index keys are symbol names, values are module paths.
                # We need to find the file that corresponds to this module_path
                # This logic is getting complex. The project_index should probably map module_path to summary.
                # For now, let's simplify: use the purpose from the plan for relevance scoring.

                # Simplified relevance: Check if module_name (which is a symbol) is mentioned in the current file's purpose
                current_file_purpose = ""
                for f_info in context.plan.get("files", []):
                    if f_info["filename"] == filename:
                        current_file_purpose = f_info["purpose"].lower()
                        break

                score = 0
                if module_name.lower() in current_file_purpose:  # if symbol is in purpose
                    score += 0.5
                if file_stem in module_name.lower():  # if symbol contains file stem
                    score += 0.3

                # Let's use the `generation_session` for full code of already generated files
                # The `project_index` from `build_generation_context` should be the *initial* state from disk.
                # The `generation_session` in the context holds the newly generated code.

                # This part needs rethink: how to get content for relevance scoring of *other* modules.
                # For now, let's assume relevance_scores are pre-calculated and we use those.
                # The `_calculate_relevance_scores` uses the initial project_index.

                score_key = f"project_index:{module_name}"  # This assumes module_name is the path
                # But project_index maps symbol to path.
                # This whole section needs to align with project_index structure.
                # For now, this will likely not work well.

                # Let's assume project_index maps module_path_str to summary string
                # And that relevance_scores are correctly calculated based on that.

                # This part of the code is likely not the primary cause of the pygame/ursina issue,
                # which is more about the Coder not seeing the *full code* of main.py or other ursina files.
                # The CODER_PROMPT uses `generated_files_code_json` for that.

            # For now, let's just pass all known symbols to simplify and ensure maximum info,
            # as the token count for just symbols is low.
            # The `CODER_PROMPT` will get full code of generated files anyway.
            # This `relevant_modules` is for the `symbol_index_json` part of the CODER_PROMPT.
            return context.project_index.copy()  # Send all known symbols

        except Exception:
            return {}

    def _filter_design_context(self, filename: str, design_context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if not design_context: return {}
            filtered_design = {}
            file_stem = Path(filename).stem.lower()
            if "classes" in design_context:
                relevant_classes = [c for c in design_context["classes"] if
                                    file_stem in c.get("file", "").lower() or filename.lower() in c.get("file",
                                                                                                        "").lower() or file_stem in c.get(
                                        "name", "").lower()]
                if relevant_classes: filtered_design["classes"] = relevant_classes
            if "functions" in design_context:
                relevant_functions = [f for f in design_context["functions"] if
                                      file_stem in f.get("file", "").lower() or filename.lower() in f.get("file",
                                                                                                          "").lower() or file_stem in f.get(
                                          "name", "").lower()]
                if relevant_functions: filtered_design["functions"] = relevant_functions
            return filtered_design
        except Exception:
            return {}

    def _filter_rag_context(self, filename: str, rag_context: str) -> str:
        try:
            if not rag_context: return ""
            chunks = rag_context.split("--- Relevant Document Snippet")
            relevant_chunks = []
            file_stem = Path(filename).stem.lower()
            for chunk in chunks:
                chunk_lower = chunk.lower()
                if (file_stem in chunk_lower or filename.lower() in chunk_lower or
                        any(word in chunk_lower for word in ['class', 'function', 'method', 'import'])):
                    relevant_chunks.append(chunk.strip())
            if not relevant_chunks and chunks: relevant_chunks = chunks[:2]
            result = "\n\n".join(relevant_chunks)
            return result[:1000] + "..." if len(result) > 1000 else result
        except Exception:
            return rag_context[:500] + "..." if len(rag_context) > 500 else rag_context

    def _get_file_dependencies(self, filename: str, context: GenerationContext) -> List[str]:
        try:
            dependencies = []
            if filename in context.generation_session:
                session_deps = context.generation_session[filename].get("dependencies", [])
                dependencies.extend(session_deps)
            for file_info in context.plan.get("files", []):
                other_filename = file_info["filename"]
                if other_filename != filename and other_filename.endswith('.py'):
                    if self._should_file_import_from(filename, other_filename, context):
                        module_name = other_filename.replace('.py', '').replace('/', '.')
                        dependencies.append(module_name)
            return list(set(dependencies))
        except Exception:
            return []

    def _should_file_import_from(self, current_file: str, other_file: str, context: GenerationContext) -> bool:
        try:
            if current_file == "main.py": return True
            current_purpose, other_purpose = "", ""
            for file_info in context.plan.get("files", []):
                if file_info["filename"] == current_file:
                    current_purpose = file_info["purpose"].lower()
                elif file_info["filename"] == other_file:
                    other_purpose = file_info["purpose"].lower()
            current_words, other_words = set(current_purpose.split()), set(other_purpose.split())
            if len(current_words.intersection(other_words)) > 1: return True
            if "service" in current_file.lower() and "core" in other_file.lower(): return True
            return False
        except Exception:
            return False

    def _extract_code_summary(self, code: str) -> str:  # This is not used anymore by project_index directly
        # Project indexer now handles symbol extraction. This can be removed or repurposed if needed for other summaries.
        return ""