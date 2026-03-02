import { useState, useEffect, useCallback } from "react";
import {
  Plus,
  ChevronDown,
  ChevronRight,
  Pencil,
  Trash2,
  X,
} from "lucide-react";
import { intelflowApi } from "../api/client";
import type {
  BriefingTopic,
  BriefingSubtopic,
  BriefingTopicCreate,
  BriefingTopicUpdate,
  BriefingSubtopicCreate,
  BriefingSubtopicUpdate,
} from "../types";

// ─── Toggle Switch ───

function ToggleSwitch({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className="relative inline-flex items-center shrink-0 transition-colors"
      style={{
        width: 36,
        height: 20,
        backgroundColor: checked
          ? "var(--if-accent)"
          : "var(--if-border-light, #3A3A3A)",
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? "not-allowed" : "pointer",
      }}
    >
      <span
        className="block transition-transform"
        style={{
          width: 16,
          height: 16,
          backgroundColor: "var(--if-bg)",
          transform: checked ? "translateX(18px)" : "translateX(2px)",
        }}
      />
    </button>
  );
}

// ─── Modal Backdrop ───

function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(0,0,0,0.7)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg border"
        style={{
          backgroundColor: "var(--if-bg-elevated)",
          borderColor: "var(--if-border)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between px-5 py-4 border-b"
          style={{ borderColor: "var(--if-border)" }}
        >
          <h2
            className="text-base font-light"
            style={{
              fontFamily: "var(--if-font-display)",
              color: "var(--if-text)",
            }}
          >
            {title}
          </h2>
          <button
            onClick={onClose}
            className="p-1 transition-colors"
            style={{ color: "var(--if-text-muted)" }}
          >
            <X size={16} />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

// ─── Form Field ───

function FormField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block mb-3">
      <span
        className="block text-xs mb-1 uppercase tracking-wider"
        style={{ color: "var(--if-text-tertiary)" }}
      >
        {label}
      </span>
      {children}
    </label>
  );
}

const inputStyle: React.CSSProperties = {
  backgroundColor: "var(--if-bg-surface)",
  borderColor: "var(--if-border)",
  color: "var(--if-text)",
};

// ─── Topic Form Modal ───

function TopicFormModal({
  open,
  onClose,
  topic,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  topic: BriefingTopic | null;
  onSave: (data: BriefingTopicCreate | BriefingTopicUpdate) => void;
}) {
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [promptTemplate, setPromptTemplate] = useState("");
  const [schedule, setSchedule] = useState("daily");

  useEffect(() => {
    if (topic) {
      setName(topic.name);
      setDisplayName(topic.display_name);
      setDescription(topic.description || "");
      setPromptTemplate(topic.prompt_template || "");
      setSchedule(topic.schedule);
    } else {
      setName("");
      setDisplayName("");
      setDescription("");
      setPromptTemplate("");
      setSchedule("daily");
    }
  }, [topic, open]);

  const handleSubmit = () => {
    if (!displayName.trim()) return;
    if (topic) {
      const update: BriefingTopicUpdate = {
        display_name: displayName,
        description: description || undefined,
        prompt_template: promptTemplate || undefined,
        schedule,
      };
      onSave(update);
    } else {
      const create: BriefingTopicCreate = {
        name: name || displayName.toLowerCase().replace(/\s+/g, "-"),
        display_name: displayName,
        description: description || undefined,
        prompt_template: promptTemplate || undefined,
        schedule,
      };
      onSave(create);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={topic ? "編輯主題" : "新增主題"}
    >
      {!topic && (
        <FormField label="識別名稱">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. tech-trends"
            className="w-full border px-3 py-2 text-sm outline-none"
            style={inputStyle}
          />
        </FormField>
      )}
      <FormField label="顯示名稱">
        <input
          type="text"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="e.g. 科技趨勢"
          className="w-full border px-3 py-2 text-sm outline-none"
          style={inputStyle}
        />
      </FormField>
      <FormField label="描述">
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          className="w-full border px-3 py-2 text-sm outline-none resize-y"
          style={inputStyle}
        />
      </FormField>
      <FormField label="Prompt 模板">
        <textarea
          value={promptTemplate}
          onChange={(e) => setPromptTemplate(e.target.value)}
          rows={3}
          placeholder="可選：用於生成 briefing 的 prompt 模板"
          className="w-full border px-3 py-2 text-sm outline-none resize-y font-mono"
          style={inputStyle}
        />
      </FormField>
      <FormField label="排程">
        <select
          value={schedule}
          onChange={(e) => setSchedule(e.target.value)}
          className="w-full border px-3 py-2 text-sm outline-none"
          style={inputStyle}
        >
          <option value="daily">每日</option>
          <option value="weekly">每週</option>
          <option value="manual">手動</option>
        </select>
      </FormField>
      <div className="flex justify-end gap-2 mt-4">
        <button
          onClick={onClose}
          className="px-4 py-2 text-sm border transition-colors"
          style={{
            borderColor: "var(--if-border)",
            color: "var(--if-text-tertiary)",
          }}
        >
          取消
        </button>
        <button
          onClick={handleSubmit}
          className="px-4 py-2 text-sm transition-colors"
          style={{
            backgroundColor: "var(--if-accent)",
            color: "var(--if-bg)",
          }}
        >
          {topic ? "儲存" : "建立"}
        </button>
      </div>
    </Modal>
  );
}

// ─── Subtopic Form Modal ───

function SubtopicFormModal({
  open,
  onClose,
  subtopic,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  subtopic: BriefingSubtopic | null;
  onSave: (data: BriefingSubtopicCreate | BriefingSubtopicUpdate) => void;
}) {
  const [name, setName] = useState("");
  const [paramsText, setParamsText] = useState("{}");
  const [parseError, setParseError] = useState("");

  useEffect(() => {
    if (subtopic) {
      setName(subtopic.name);
      setParamsText(JSON.stringify(subtopic.parameters, null, 2));
    } else {
      setName("");
      setParamsText("{}");
    }
    setParseError("");
  }, [subtopic, open]);

  const handleSubmit = () => {
    if (!name.trim()) return;
    let parameters: Record<string, unknown>;
    try {
      parameters = JSON.parse(paramsText);
      setParseError("");
    } catch {
      setParseError("JSON 格式錯誤");
      return;
    }
    onSave({ name, parameters });
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={subtopic ? "編輯子分類" : "新增子分類"}
    >
      <FormField label="名稱">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. 台北"
          className="w-full border px-3 py-2 text-sm outline-none"
          style={inputStyle}
        />
      </FormField>
      <FormField label="參數 (JSON)">
        <textarea
          value={paramsText}
          onChange={(e) => {
            setParamsText(e.target.value);
            setParseError("");
          }}
          rows={4}
          className="w-full border px-3 py-2 text-sm outline-none resize-y font-mono"
          style={inputStyle}
        />
        {parseError && (
          <p className="text-xs mt-1" style={{ color: "#E06C75" }}>
            {parseError}
          </p>
        )}
      </FormField>
      <div className="flex justify-end gap-2 mt-4">
        <button
          onClick={onClose}
          className="px-4 py-2 text-sm border transition-colors"
          style={{
            borderColor: "var(--if-border)",
            color: "var(--if-text-tertiary)",
          }}
        >
          取消
        </button>
        <button
          onClick={handleSubmit}
          className="px-4 py-2 text-sm transition-colors"
          style={{
            backgroundColor: "var(--if-accent)",
            color: "var(--if-bg)",
          }}
        >
          {subtopic ? "儲存" : "建立"}
        </button>
      </div>
    </Modal>
  );
}

// ─── Subtopic Row ───

function SubtopicRow({
  subtopic,
  topicId,
  onToggle,
  onEdit,
  onDelete,
}: {
  subtopic: BriefingSubtopic;
  topicId: string;
  onToggle: (topicId: string, subtopicId: string) => void;
  onEdit: (topicId: string, subtopic: BriefingSubtopic) => void;
  onDelete: (topicId: string, subtopicId: string) => void;
}) {
  const paramEntries = Object.entries(subtopic.parameters);
  return (
    <div
      className="flex items-center gap-3 px-4 py-3 border-t"
      style={{ borderColor: "var(--if-border)" }}
    >
      <div className="flex-1 min-w-0">
        <span className="text-sm" style={{ color: "var(--if-text)" }}>
          {subtopic.name}
        </span>
        {paramEntries.length > 0 && (
          <span
            className="ml-2 text-xs"
            style={{ color: "var(--if-text-muted)" }}
          >
            {paramEntries.map(([k, v]) => `${k}=${String(v)}`).join(", ")}
          </span>
        )}
      </div>
      <ToggleSwitch
        checked={subtopic.enabled}
        onChange={() => onToggle(topicId, subtopic.id)}
      />
      <button
        onClick={() => onEdit(topicId, subtopic)}
        className="p-1.5 transition-colors"
        style={{ color: "var(--if-text-muted)" }}
        title="編輯"
      >
        <Pencil size={14} />
      </button>
      <button
        onClick={() => {
          if (confirm("確定刪除此子分類？")) onDelete(topicId, subtopic.id);
        }}
        className="p-1.5 transition-colors"
        style={{ color: "#E06C75" }}
        title="刪除"
      >
        <Trash2 size={14} />
      </button>
    </div>
  );
}

// ─── Topic Card ───

function TopicCard({
  topic,
  expanded,
  onToggleExpand,
  onToggleEnabled,
  onEdit,
  onDelete,
  onToggleSubtopic,
  onEditSubtopic,
  onDeleteSubtopic,
  onAddSubtopic,
}: {
  topic: BriefingTopic;
  expanded: boolean;
  onToggleExpand: () => void;
  onToggleEnabled: (id: string) => void;
  onEdit: (topic: BriefingTopic) => void;
  onDelete: (id: string) => void;
  onToggleSubtopic: (topicId: string, subtopicId: string) => void;
  onEditSubtopic: (topicId: string, subtopic: BriefingSubtopic) => void;
  onDeleteSubtopic: (topicId: string, subtopicId: string) => void;
  onAddSubtopic: (topicId: string) => void;
}) {
  const scheduleLabels: Record<string, string> = {
    daily: "每日",
    weekly: "每週",
    manual: "手動",
  };

  return (
    <div
      className="border transition-colors"
      style={{
        backgroundColor: "var(--if-bg-elevated)",
        borderColor: expanded
          ? "var(--if-accent)"
          : "var(--if-border)",
      }}
    >
      {/* Card Header */}
      <div className="px-4 py-4">
        <div className="flex items-start gap-3">
          <button
            onClick={onToggleExpand}
            className="mt-0.5 p-0.5 shrink-0 transition-colors"
            style={{ color: "var(--if-text-muted)" }}
          >
            {expanded ? (
              <ChevronDown size={16} />
            ) : (
              <ChevronRight size={16} />
            )}
          </button>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <h3
                className="text-sm font-medium truncate"
                style={{ color: "var(--if-text)" }}
              >
                {topic.display_name}
              </h3>
              <span
                className="shrink-0 text-[10px] uppercase tracking-wider px-1.5 py-0.5"
                style={{
                  backgroundColor: "var(--if-bg-surface)",
                  color: "var(--if-text-dim)",
                }}
              >
                {scheduleLabels[topic.schedule] || topic.schedule}
              </span>
            </div>
            {topic.description && (
              <p
                className="text-xs line-clamp-2"
                style={{ color: "var(--if-text-tertiary)" }}
              >
                {topic.description}
              </p>
            )}
            <div className="flex items-center gap-3 mt-2">
              <span
                className="text-[10px] uppercase tracking-wider"
                style={{ color: "var(--if-text-dim)" }}
              >
                {topic.name}
              </span>
              {topic.subtopics.length > 0 && (
                <span
                  className="text-[10px]"
                  style={{ color: "var(--if-text-muted)" }}
                >
                  {topic.subtopics.length} 子分類
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <ToggleSwitch
              checked={topic.enabled}
              onChange={() => onToggleEnabled(topic.id)}
            />
            <button
              onClick={() => onEdit(topic)}
              className="p-1.5 transition-colors"
              style={{ color: "var(--if-text-muted)" }}
              title="編輯"
            >
              <Pencil size={14} />
            </button>
            <button
              onClick={() => {
                if (confirm(`確定刪除「${topic.display_name}」？`))
                  onDelete(topic.id);
              }}
              className="p-1.5 transition-colors"
              style={{ color: "#E06C75" }}
              title="刪除"
            >
              <Trash2 size={14} />
            </button>
          </div>
        </div>
      </div>

      {/* Expanded: Subtopics */}
      {expanded && (
        <div
          className="border-t"
          style={{
            borderColor: "var(--if-border)",
            backgroundColor: "var(--if-bg-surface)",
          }}
        >
          {topic.subtopics.length === 0 ? (
            <div
              className="px-4 py-3 text-xs"
              style={{ color: "var(--if-text-dim)" }}
            >
              尚無子分類
            </div>
          ) : (
            topic.subtopics.map((sub, i) => (
              <SubtopicRow
                key={sub.id}
                subtopic={sub}
                topicId={topic.id}
                onToggle={onToggleSubtopic}
                onEdit={onEditSubtopic}
                onDelete={onDeleteSubtopic}
              />
            ))
          )}
          <button
            onClick={() => onAddSubtopic(topic.id)}
            className="flex items-center gap-1.5 w-full px-4 py-2.5 text-xs border-t transition-colors"
            style={{
              borderColor: "var(--if-border)",
              color: "var(--if-accent)",
            }}
          >
            <Plus size={12} />
            新增子分類
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Main Page ───

export default function BriefingSettings() {
  const [topics, setTopics] = useState<BriefingTopic[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedTopics, setExpandedTopics] = useState<Set<string>>(
    new Set(),
  );

  // Topic modal
  const [topicModalOpen, setTopicModalOpen] = useState(false);
  const [editingTopic, setEditingTopic] = useState<BriefingTopic | null>(
    null,
  );

  // Subtopic modal
  const [subtopicModalOpen, setSubtopicModalOpen] = useState(false);
  const [subtopicContext, setSubtopicContext] = useState<{
    topicId: string;
    subtopic: BriefingSubtopic | null;
  }>({ topicId: "", subtopic: null });

  const fetchTopics = useCallback(async () => {
    try {
      const res = await intelflowApi.listBriefingTopics();
      setTopics(res.items);
    } catch (err) {
      console.error("Failed to fetch briefing topics", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTopics();
  }, [fetchTopics]);

  // ─── Topic CRUD ───

  const handleToggleEnabled = async (id: string) => {
    try {
      const updated = await intelflowApi.toggleBriefingTopic(id);
      setTopics((prev) =>
        prev.map((t) => (t.id === id ? { ...t, enabled: updated.enabled } : t)),
      );
    } catch (err) {
      console.error("Toggle failed", err);
    }
  };

  const handleSaveTopic = async (
    data: BriefingTopicCreate | BriefingTopicUpdate,
  ) => {
    try {
      if (editingTopic) {
        await intelflowApi.updateBriefingTopic(
          editingTopic.id,
          data as BriefingTopicUpdate,
        );
      } else {
        await intelflowApi.createBriefingTopic(data as BriefingTopicCreate);
      }
      setTopicModalOpen(false);
      setEditingTopic(null);
      await fetchTopics();
    } catch (err) {
      console.error("Save topic failed", err);
    }
  };

  const handleDeleteTopic = async (id: string) => {
    try {
      await intelflowApi.deleteBriefingTopic(id);
      setTopics((prev) => prev.filter((t) => t.id !== id));
      setExpandedTopics((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    } catch (err) {
      console.error("Delete topic failed", err);
    }
  };

  // ─── Subtopic CRUD ───

  const handleToggleSubtopic = async (
    topicId: string,
    subtopicId: string,
  ) => {
    const topic = topics.find((t) => t.id === topicId);
    const sub = topic?.subtopics.find((s) => s.id === subtopicId);
    if (!sub) return;
    try {
      await intelflowApi.updateBriefingSubtopic(topicId, subtopicId, {
        enabled: !sub.enabled,
      });
      await fetchTopics();
    } catch (err) {
      console.error("Toggle subtopic failed", err);
    }
  };

  const handleSaveSubtopic = async (
    data: BriefingSubtopicCreate | BriefingSubtopicUpdate,
  ) => {
    try {
      if (subtopicContext.subtopic) {
        await intelflowApi.updateBriefingSubtopic(
          subtopicContext.topicId,
          subtopicContext.subtopic.id,
          data as BriefingSubtopicUpdate,
        );
      } else {
        await intelflowApi.addBriefingSubtopic(
          subtopicContext.topicId,
          data as BriefingSubtopicCreate,
        );
      }
      setSubtopicModalOpen(false);
      await fetchTopics();
    } catch (err) {
      console.error("Save subtopic failed", err);
    }
  };

  const handleDeleteSubtopic = async (
    topicId: string,
    subtopicId: string,
  ) => {
    try {
      await intelflowApi.deleteBriefingSubtopic(topicId, subtopicId);
      await fetchTopics();
    } catch (err) {
      console.error("Delete subtopic failed", err);
    }
  };

  // ─── Expand / Collapse ───

  const toggleExpand = (id: string) => {
    setExpandedTopics((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Sort by priority
  const sorted = [...topics].sort((a, b) => a.priority - b.priority);

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1
            className="text-2xl sm:text-3xl font-light"
            style={{
              fontFamily: "var(--if-font-display)",
              color: "var(--if-text)",
            }}
          >
            Briefing 設定
          </h1>
          <p
            className="text-sm mt-1"
            style={{ color: "var(--if-text-tertiary)" }}
          >
            管理每日簡報主題與子分類
          </p>
        </div>
        <button
          onClick={() => {
            setEditingTopic(null);
            setTopicModalOpen(true);
          }}
          className="flex items-center gap-1.5 px-4 py-2.5 text-sm shrink-0 transition-colors"
          style={{
            backgroundColor: "var(--if-accent)",
            color: "var(--if-bg)",
          }}
        >
          <Plus size={14} />
          新增主題
        </button>
      </div>

      {/* Topic Grid */}
      {loading ? (
        <div className="flex items-center justify-center h-32">
          <div
            className="h-5 w-5 animate-spin border-2 border-t-transparent"
            style={{
              borderColor: "var(--if-accent)",
              borderTopColor: "transparent",
            }}
          />
        </div>
      ) : sorted.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 sm:gap-4">
          {sorted.map((topic) => (
            <TopicCard
              key={topic.id}
              topic={topic}
              expanded={expandedTopics.has(topic.id)}
              onToggleExpand={() => toggleExpand(topic.id)}
              onToggleEnabled={handleToggleEnabled}
              onEdit={(t) => {
                setEditingTopic(t);
                setTopicModalOpen(true);
              }}
              onDelete={handleDeleteTopic}
              onToggleSubtopic={handleToggleSubtopic}
              onEditSubtopic={(topicId, sub) => {
                setSubtopicContext({ topicId, subtopic: sub });
                setSubtopicModalOpen(true);
              }}
              onDeleteSubtopic={handleDeleteSubtopic}
              onAddSubtopic={(topicId) => {
                setSubtopicContext({ topicId, subtopic: null });
                setSubtopicModalOpen(true);
              }}
            />
          ))}
        </div>
      ) : (
        <div
          className="py-16 text-center border"
          style={{
            borderColor: "var(--if-border)",
            backgroundColor: "var(--if-bg-elevated)",
          }}
        >
          <p className="text-sm mb-1" style={{ color: "var(--if-text-dim)" }}>
            尚未建立任何 Briefing 主題
          </p>
          <p
            className="text-xs"
            style={{ color: "var(--if-text-muted)" }}
          >
            點擊上方「新增主題」開始設定每日簡報
          </p>
        </div>
      )}

      {/* Modals */}
      <TopicFormModal
        open={topicModalOpen}
        onClose={() => {
          setTopicModalOpen(false);
          setEditingTopic(null);
        }}
        topic={editingTopic}
        onSave={handleSaveTopic}
      />
      <SubtopicFormModal
        open={subtopicModalOpen}
        onClose={() => setSubtopicModalOpen(false)}
        subtopic={subtopicContext.subtopic}
        onSave={handleSaveSubtopic}
      />
    </div>
  );
}
