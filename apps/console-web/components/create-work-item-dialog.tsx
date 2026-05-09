"use client";

import { type FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "./ui/button";
import { Dialog, DialogFooter, DialogTitle } from "./ui/dialog";
import { createWorkItem, type CreateWorkItemPayload } from "../lib/console-api";

const EMPTY_FORM: CreateWorkItemPayload = {
  repo: "",
  title: "",
  description: "",
  type: "feature",
  priority: "medium",
};

export function CreateWorkItemDialog() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<CreateWorkItemPayload>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function handleChange(
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>
  ) {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!form.repo.trim() || !form.title.trim() || !form.description.trim()) {
      setError("repo, title, description 均为必填项");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const result = await createWorkItem(form);
      if (!result.success) {
        setError(result.error ?? "创建失败");
        return;
      }
      setOpen(false);
      setForm(EMPTY_FORM);
      router.refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <Button onClick={() => { setError(null); setOpen(true); }}>+ 新建任务</Button>

      {open ? (
        <Dialog onClose={() => setOpen(false)} titleId="create-wi-dialog-title">
          <DialogTitle id="create-wi-dialog-title">新建开发任务</DialogTitle>
          <form onSubmit={handleSubmit}>
            {error ? <p className="form-error">{error}</p> : null}

            <div className="form-field">
              <label className="form-label" htmlFor="wi-repo">Repo *</label>
              <input
                id="wi-repo"
                name="repo"
                className="form-input"
                placeholder="org/repo-name"
                value={form.repo}
                onChange={handleChange}
                required
              />
            </div>

            <div className="form-field">
              <label className="form-label" htmlFor="wi-title">Title *</label>
              <input
                id="wi-title"
                name="title"
                className="form-input"
                placeholder="Fix auth bug"
                value={form.title}
                onChange={handleChange}
                required
              />
            </div>

            <div className="form-field">
              <label className="form-label" htmlFor="wi-description">Description *</label>
              <textarea
                id="wi-description"
                name="description"
                className="form-textarea"
                placeholder="Describe the goal and acceptance criteria…"
                value={form.description}
                onChange={handleChange}
                required
              />
            </div>

            <div className="form-field">
              <label className="form-label" htmlFor="wi-type">Type</label>
              <select id="wi-type" name="type" className="form-select" value={form.type} onChange={handleChange}>
                <option value="feature">Feature</option>
                <option value="bugfix">Bugfix</option>
                <option value="incident">Incident</option>
                <option value="ops">Ops</option>
                <option value="experiment">Experiment</option>
              </select>
            </div>

            <div className="form-field">
              <label className="form-label" htmlFor="wi-priority">Priority</label>
              <select id="wi-priority" name="priority" className="form-select" value={form.priority} onChange={handleChange}>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>取消</Button>
              <Button type="submit" disabled={loading}>{loading ? "提交中…" : "创建任务"}</Button>
            </DialogFooter>
          </form>
        </Dialog>
      ) : null}
    </>
  );
}
