import { useState } from "react";
import { Search } from "lucide-react";
import { useTopics } from "../hooks/useIntelflow";
import TopicCard from "../components/TopicCard";
import TagBadge from "../components/TagBadge";

const MAX_VISIBLE_TAGS = 10;

export default function TopicsOverview() {
  const { topics, total, loading, activeTopic, setActiveTopic } = useTopics();
  const [searchText, setSearchText] = useState("");
  const [tagsExpanded, setTagsExpanded] = useState(false);

  // All topics sorted by report_count for tag filter
  const sortedByCount = [...topics].sort((a, b) => b.report_count - a.report_count);
  const visibleTags = tagsExpanded ? sortedByCount : sortedByCount.slice(0, MAX_VISIBLE_TAGS);
  const hiddenCount = topics.length - MAX_VISIBLE_TAGS;

  // Filter logic
  let filtered = topics;
  if (activeTopic) {
    filtered = topics.filter((t) => t.name === activeTopic);
  }
  if (searchText) {
    const q = searchText.toLowerCase();
    filtered = filtered.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        (t.display_name && t.display_name.toLowerCase().includes(q)),
    );
  }

  // Sort by report_count desc
  const sorted = [...filtered].sort((a, b) => b.report_count - a.report_count);

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
      {/* Header */}
      <div>
        <h1
          className="text-2xl sm:text-3xl font-light"
          style={{ fontFamily: "var(--if-font-display)", color: "var(--if-text)" }}
        >
          主題總覽
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--if-text-tertiary)" }}>
          共 {total} 個主題
        </p>
      </div>

      {/* Search */}
      <div
        className="flex items-center gap-3 border px-4 py-3"
        style={{
          backgroundColor: "var(--if-bg-elevated)",
          borderColor: "var(--if-border)",
        }}
      >
        <Search size={16} style={{ color: "var(--if-text-muted)" }} />
        <input
          type="text"
          placeholder="搜尋主題名稱..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          className="flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--if-text-dim)]"
          style={{ color: "var(--if-text)" }}
        />
      </div>

      {/* Top tag filters */}
      {topics.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <TagBadge
            tag="全部"
            active={!activeTopic}
            onClick={() => setActiveTopic(null)}
          />
          {visibleTags.map((topic) => (
            <TagBadge
              key={topic.id}
              tag={topic.display_name || topic.name}
              active={activeTopic === topic.name}
              onClick={() =>
                setActiveTopic(activeTopic === topic.name ? null : topic.name)
              }
            />
          ))}
          {hiddenCount > 0 && (
            <button
              onClick={() => setTagsExpanded(!tagsExpanded)}
              className="shrink-0 text-xs px-2.5 py-2 border transition-colors min-h-[36px]"
              style={{
                borderColor: "var(--if-border)",
                color: "var(--if-text-dim)",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "var(--if-accent)";
                e.currentTarget.style.color = "var(--if-accent)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "var(--if-border)";
                e.currentTarget.style.color = "var(--if-text-dim)";
              }}
            >
              {tagsExpanded ? "收合" : `+${hiddenCount}`}
            </button>
          )}
        </div>
      )}

      {/* Card grid — 1 col on mobile, 2 on sm, 3 on xl */}
      {loading ? (
        <div className="flex items-center justify-center h-32">
          <div
            className="h-5 w-5 animate-spin border-2 border-t-transparent"
            style={{ borderColor: "var(--if-accent)", borderTopColor: "transparent" }}
          />
        </div>
      ) : sorted.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 sm:gap-4">
          {sorted.map((topic) => (
            <TopicCard key={topic.id} topic={topic} />
          ))}
        </div>
      ) : (
        <div className="py-12 text-center text-sm" style={{ color: "var(--if-text-dim)" }}>
          {searchText ? "無搜尋結果" : "尚無主題"}
        </div>
      )}
    </div>
  );
}
