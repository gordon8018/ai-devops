#!/usr/bin/env python3
"""
Ralph Executor Wrapper - Part 1
"""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class RalphRunnerError(Exception):
    pass



try:
    from quality_gate import QualityGate
except ImportError:
    from orchestrator.bin.quality_gate import QualityGate

try:
    from obsidian_sync import ObsidianSync
except ImportError:
    from orchestrator.bin.obsidian_sync import ObsidianSync

try:
    from gbrain_indexer import GbrainIndexer
except ImportError:
    from orchestrator.bin.gbrain_indexer import GbrainIndexer

try:
    from gbrain_retriever import GbrainRetriever
except ImportError:
    from orchestrator.bin.gbrain_retriever import GbrainRetriever

try:
    from context_assembler import ContextAssembler
except ImportError:
    from orchestrator.bin.context_assembler import ContextAssembler

class RalphRunner:
    def __init__(self, ralph_dir: str | Path, ralph_sh_path: str | Path = None, tool: str = "claude"):
        self.ralph_dir = Path(ralph_dir)
        self.ralph_dir.mkdir(parents=True, exist_ok=True)
        
        if ralph_sh_path is None:
            ralph_sh_path = Path.home() / ".openclaw/workspace-alpha/ralph/ralph.sh"
        
        self.ralph_sh_path = Path(ralph_sh_path)
        self.tool = tool
        
        if not self.ralph_sh_path.exists():
            raise RalphRunnerError(f"ralph.sh not found at {self.ralph_sh_path}")
    
    def run(self, max_iterations: int = 10, timeout: int = 7200, capture_output: bool = True, background: bool = False) -> Dict[str, Any]:
        cmd = [str(self.ralph_sh_path), "--tool", self.tool, str(max_iterations)]
        
        if background:
            process = subprocess.Popen(
                cmd,
                cwd=str(self.ralph_dir),
                stdout=subprocess.PIPE if capture_output else None,
                stderr=subprocess.PIPE if capture_output else None,
                start_new_session=True
            )
            return {
                "success": True,
                "pid": process.pid,
                "status": "running_in_background",
                "command": " ".join(cmd),
                "started_at": time.time()
            }
        
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.ralph_dir),
                capture_output=capture_output,
                text=True,
                timeout=timeout
            )
            
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout if capture_output else "",
                "stderr": result.stderr if capture_output else "",
                "completed_at": time.time()
            }
        
        except subprocess.TimeoutExpired:
            raise RalphRunnerError(f"ralph execution timed out after {timeout} seconds")
        except FileNotFoundError:
            raise RalphRunnerError(f"ralph.sh not found or not executable")
        except Exception as e:
            raise RalphRunnerError(f"Failed to run ralph: {e}")
    
    def parse_progress(self) -> Dict[str, Any]:
        progress_file = self.ralph_dir / "progress.txt"
        
        if not progress_file.exists():
            return {
                "exists": False,
                "iterations": 0,
                "current_story": None,
                "last_activity": None
            }
        
        content = progress_file.read_text()
        
        iterations = 0
        current_story = None
        last_activity = None
        
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith("##"):
                iterations += 1
                parts = line.split("-")
                if len(parts) > 1:
                    current_story = parts[-1].strip()
            elif line and not line.startswith("#") and iterations > 0:
                last_activity = line[:100]
        
        return {
            "exists": True,
            "iterations": iterations,
            "current_story": current_story,
            "last_activity": last_activity,
            "file_size": len(content)
        }
    
    def parse_prd_json(self) -> Dict[str, Any]:
        prd_file = self.ralph_dir / "prd.json"
        
        if not prd_file.exists():
            return {"exists": False}
        
        try:
            with open(prd_file, 'r') as f:
                prd = json.load(f)
            
            stories = prd.get("userStories", [])
            total = len(stories)
            completed = sum(1 for s in stories if s.get("passes", False))
            
            return {
                "exists": True,
                "project": prd.get("project"),
                "branchName": prd.get("branchName"),
                "total_stories": total,
                "completed_stories": completed,
                "progress_percent": (completed / total * 100) if total > 0 else 0,
                "stories": [
                    {"id": s.get("id"), "title": s.get("title"), "passes": s.get("passes", False)}
                    for s in stories
                ]
            }
        
        except (json.JSONDecodeError, IOError) as e:
            raise RalphRunnerError(f"Failed to parse prd.json: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        prd_info = self.parse_prd_json()
        progress_info = self.parse_progress()
        
        if not prd_info.get("exists"):
            status = "not_started"
        elif prd_info.get("progress_percent", 0) == 100:
            status = "completed"
        elif progress_info.get("iterations", 0) > 0:
            status = "running"
        else:
            status = "queued"
        
        return {
            "status": status,
            "prd": prd_info,
            "progress": progress_info,
            "updated_at": time.time()
        }
    
    def wait_for_completion(self, poll_interval: int = 30, timeout: int = 7200) -> Dict[str, Any]:
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status = self.get_status()
            
            if status["status"] in ("completed", "failed"):
                return status
            
            time.sleep(poll_interval)
        
        raise RalphRunnerError(f"Timed out waiting for ralph completion after {timeout} seconds")
    
    def save_prd_json(self, prd: Dict[str, Any]) -> None:
        prd_file = self.ralph_dir / "prd.json"
        
        with open(prd_file, 'w', encoding='utf-8') as f:
            json.dump(prd, f, indent=2, ensure_ascii=False)




    def run_with_quality_gate(
        self,
        task_id: str,
        max_iterations: int = 10,
        timeout: int = 7200,
        repo_dir: Optional[Path] = None,
        quality_threshold: float = 8.0,
        enable_quality_gate: bool = True
    ) -> Dict[str, Any]:
        """Run ralph with quality gate enforcement
        
        Flow: ralph execution -> quality gate -> CI check -> completion/retry
        """
        # Execute ralph
        result = self.run(max_iterations=max_iterations, timeout=timeout)
        
        if not result["success"]:
            return {
                "ralph_result": result,
                "quality_gate": None,
                "final_status": "ralph_failed"
            }
        
        if not enable_quality_gate or not repo_dir:
            return {
                "ralph_result": result,
                "quality_gate": None,
                "final_status": "completed_no_qg"
            }
        
        # Run quality gate
        try:
            gate = QualityGate()
            qg_result = gate.enforce_quality_gate(
                task_id=task_id,
                repo_dir=repo_dir,
                threshold=quality_threshold,
                retry_on_failure=True
            )
            
            final_status = "completed" if qg_result["passed"] else "quality_gate_failed"
            
            return {
                "ralph_result": result,
                "quality_gate": qg_result,
                "final_status": final_status
            }
        
        except Exception as e:
            return {
                "ralph_result": result,
                "quality_gate": {"error": str(e)},
                "final_status": "quality_gate_error"
            }

    def inject_historical_context(
        self,
        task_spec: Dict[str, Any],
        top_n: int = 3,
        min_relevance: float = 0.5,
        compact: bool = False,
    ) -> Dict[str, Any]:
        """Phase 4+: Retrieve and inject historical context into PRD.

        Args:
            task_spec: Current TaskSpec dictionary
            top_n: Maximum number of historical tasks to retrieve
            min_relevance: Minimum relevance score threshold
            compact: Use compact mode for space-constrained scenarios

        Returns:
            Result dictionary with context and retrieval info
        """
        retrieval_result = {
            "success": False,
            "context": "",
            "retrieved_tasks": [],
            "error": None,
        }

        try:
            # Step 1: Retrieve historical tasks
            retriever = GbrainRetriever(top_n=top_n, min_relevance=min_relevance)
            historical_tasks = retriever.retrieve(task_spec)

            retrieval_result["retrieved_tasks"] = [t.to_dict() for t in historical_tasks]

            # Step 2: Assemble context
            if historical_tasks:
                assembler = ContextAssembler()
                if compact:
                    context = assembler.assemble_compact(task_spec, historical_tasks)
                else:
                    context = assembler.assemble(task_spec, historical_tasks)

                retrieval_result["context"] = context
                retrieval_result["success"] = True
            else:
                retrieval_result["context"] = "未找到相关历史任务"
                retrieval_result["success"] = True

        except Exception as e:
            retrieval_result["error"] = str(e)
            retrieval_result["context"] = ""  # Continue with empty context

        return retrieval_result

    def run_full_pipeline(
        self,
        task_id: str,
        max_iterations: int = 10,
        timeout: int = 7200,
        repo_dir: Optional[Path] = None,
        quality_threshold: float = 8.0,
        enable_quality_gate: bool = True,
        enable_obsidian_sync: bool = True,
        enable_gbrain_indexer: bool = True,
        agents_md_path: Optional[Path] = None,
        project: str = "ai-devops",
        task_type: str = "general",
        task_spec: Optional[Dict[str, Any]] = None,
        enable_historical_context: bool = False,
        historical_context_top_n: int = 3,
        historical_context_min_relevance: float = 0.5,
        compact_context: bool = False,
    ) -> Dict[str, Any]:
        """Run complete pipeline: context_injection → ralph → quality_gate → CI → obsidian_sync → gbrain_indexer → complete"""
        pipeline_result = {
            "task_id": task_id,
            "started_at": time.time(),
            "historical_context": None,
            "ralph": None,
            "quality_gate": None,
            "obsidian_sync": None,
            "gbrain_indexer": None,
            "final_status": "unknown",
        }

        # Phase 4+: Step 0 - Historical context injection
        if enable_historical_context and task_spec:
            context_result = self.inject_historical_context(
                task_spec=task_spec,
                top_n=historical_context_top_n,
                min_relevance=historical_context_min_relevance,
                compact=compact_context,
            )
            pipeline_result["historical_context"] = context_result

            # Inject context into prd.json
            prd_info = self.parse_prd_json()
            if prd_info.get("exists"):
                try:
                    prd_file = self.ralph_dir / "prd.json"
                    with open(prd_file, 'r', encoding='utf-8') as f:
                        prd = json.load(f)
                    prd["context"] = context_result.get("context", "")
                    with open(prd_file, 'w', encoding='utf-8') as f:
                        json.dump(prd, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    pipeline_result["historical_context"]["inject_error"] = str(e)

        # Step 1: Ralph execution + quality gate
        qg_result = self.run_with_quality_gate(
            task_id=task_id,
            max_iterations=max_iterations,
            timeout=timeout,
            repo_dir=repo_dir,
            quality_threshold=quality_threshold,
            enable_quality_gate=enable_quality_gate,
        )
        pipeline_result["ralph"] = qg_result["ralph_result"]
        pipeline_result["quality_gate"] = qg_result.get("quality_gate")

        if qg_result["final_status"] not in ("completed", "completed_no_qg"):
            pipeline_result["final_status"] = qg_result["final_status"]
            return pipeline_result

        # Step 2: Obsidian sync
        if enable_obsidian_sync:
            try:
                syncer = ObsidianSync()
                sync_result = syncer.full_sync(
                    ralph_dir=self.ralph_dir,
                    task_id=task_id,
                    agents_md_path=agents_md_path,
                )
                pipeline_result["obsidian_sync"] = sync_result
            except Exception as e:
                pipeline_result["obsidian_sync"] = {"success": False, "error": str(e)}

        # Step 3: gbrain indexing
        if enable_gbrain_indexer:
            try:
                indexer = GbrainIndexer()
                idx_result = indexer.index_task_artifacts(
                    task_id=task_id,
                    artifact_dir=self.ralph_dir,
                    project=project,
                    task_type=task_type,
                )
                pipeline_result["gbrain_indexer"] = idx_result
            except Exception as e:
                pipeline_result["gbrain_indexer"] = {"success": False, "error": str(e)}

        pipeline_result["final_status"] = "completed"
        pipeline_result["completed_at"] = time.time()
        return pipeline_result

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("RalphRunner CLI")
        print("Usage:")
        print("  ralph_runner.py run <ralph_dir> [max_iterations]")
        print("  ralph_runner.py status <ralph_dir>")
        print("  ralph_runner.py wait <ralph_dir> [poll_interval] [timeout]")
        sys.exit(0)
    
    command = sys.argv[1]
    
    try:
        if command == "run":
            ralph_dir = sys.argv[2]
            max_iter = int(sys.argv[3]) if len(sys.argv) > 3 else 10
            
            runner = RalphRunner(ralph_dir)
            result = runner.run(max_iterations=max_iter)
            
            print(json.dumps(result, indent=2))
        
        elif command == "status":
            ralph_dir = sys.argv[2]
            
            runner = RalphRunner(ralph_dir)
            status = runner.get_status()
            
            print(json.dumps(status, indent=2))
        
        elif command == "wait":
            ralph_dir = sys.argv[2]
            poll_interval = int(sys.argv[3]) if len(sys.argv) > 3 else 30
            timeout = int(sys.argv[4]) if len(sys.argv) > 4 else 7200
            
            runner = RalphRunner(ralph_dir)
            status = runner.wait_for_completion(poll_interval, timeout)
            
            print(json.dumps(status, indent=2))
        
        else:
            print(f"Unknown command: {command}")
            sys.exit(1)
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
