import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowLeft, Calendar, Tag, ExternalLink, BookOpen, ChevronDown, ChevronUp } from "lucide-react";
import { useReportDetail } from "../hooks/useIntelflow";
import TagBadge from "../components/TagBadge";

/* ─── Collapsible sidebar section for mobile ─── */
function SideSection({
  title,
  icon,
  defaultOpen = false,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div
      className="border"
      style={{
        backgroundColor: "var(--if-bg-elevated)",
        borderColor: "var(--if-border)",
      }}
    >
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center justify-between w-full px-4 sm:px-5 py-3 sm:py-4 text-left"
      >
        <h3
          className="text-xs uppercase tracking-widest flex items-center gap-2"
          style={{ color: "var(--if-text-tertiary)" }}
        >
          {icon}
          {title}
        </h3>
        <span style={{ color: "var(--if-text-muted)" }}>
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </span>
      </button>
      {open && (
        <div className="px-4 sm:px-5 pb-4 sm:pb-5">
          {children}
        </div>
      )}
    </div>
  );
}

export default function ReportDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { report, loading } = useReportDetail(id);

  if (loading || !report) {
    return (
      <div className="flex items-center justify-center h-64">
        <div
          className="h-6 w-6 animate-spin border-2 border-t-transparent"
          style={{ borderColor: "var(--if-accent)", borderTopColor: "transparent" }}
        />
      </div>
    );
  }

  const date = new Date(report.created_at).toLocaleDateString("zh-TW", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  const hasSideContent =
    (report.sources && report.sources.length > 0) ||
    report.tags.length > 0 ||
    (report.topics && report.topics.length > 0);

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
      {/* Breadcrumb */}
      <button
        onClick={() => navigate("/intelflow/reports")}
        className="flex items-center gap-2 text-sm min-h-[44px] sm:min-h-0"
        style={{ color: "var(--if-text-tertiary)" }}
        onMouseEnter={(e) => {
          e.currentTarget.style.color = "var(--if-accent)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.color = "var(--if-text-tertiary)";
        }}
      >
        <ArrowLeft size={14} />
        研究報告
      </button>

      {/* Title + meta */}
      <div>
        <h1
          className="text-xl sm:text-2xl xl:text-3xl font-light leading-tight"
          style={{ fontFamily: "var(--if-font-display)", color: "var(--if-text)" }}
        >
          {report.title}
        </h1>
        <div className="flex items-center flex-wrap gap-3 mt-2 sm:mt-3">
          <span className="flex items-center gap-1.5 text-xs" style={{ color: "var(--if-text-dim)" }}>
            <Calendar size={12} />
            {date}
          </span>
          {report.skill_name && (
            <span
              className="text-xs px-2 py-0.5 border"
              style={{ borderColor: "var(--if-accent)", color: "var(--if-accent)" }}
            >
              {report.skill_name}
            </span>
          )}
        </div>
      </div>

      {/* Two-column layout on xl, stacked on smaller screens */}
      <div className="flex flex-col xl:flex-row gap-5 sm:gap-6">
        {/* Left — main content */}
        <div className="flex-1 min-w-0 space-y-5 sm:space-y-6">
          {/* Markdown content */}
          <div
            className="border p-4 sm:p-6 xl:p-8"
            style={{
              backgroundColor: "var(--if-bg-elevated)",
              borderColor: "var(--if-border)",
            }}
          >
            <article
              className="prose prose-invert max-w-none text-sm leading-relaxed"
              style={{
                color: "var(--if-text-secondary)",
                fontFamily: "var(--if-font-ui)",
              }}
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  h1: ({ children }) => (
                    <h1
                      className="text-xl sm:text-2xl font-light mt-6 sm:mt-8 mb-3 sm:mb-4"
                      style={{ fontFamily: "var(--if-font-display)", color: "var(--if-text)" }}
                    >
                      {children}
                    </h1>
                  ),
                  h2: ({ children }) => (
                    <h2
                      className="text-lg sm:text-xl font-light mt-5 sm:mt-6 mb-2 sm:mb-3"
                      style={{ fontFamily: "var(--if-font-display)", color: "var(--if-text)" }}
                    >
                      {children}
                    </h2>
                  ),
                  h3: ({ children }) => (
                    <h3
                      className="text-base sm:text-lg font-medium mt-4 sm:mt-5 mb-2"
                      style={{ color: "var(--if-text)" }}
                    >
                      {children}
                    </h3>
                  ),
                  p: ({ children }) => (
                    <p className="text-sm sm:text-base leading-relaxed my-3" style={{ color: "var(--if-text-secondary)" }}>
                      {children}
                    </p>
                  ),
                  a: ({ href, children }) => (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline underline-offset-2"
                      style={{ color: "var(--if-accent)" }}
                    >
                      {children}
                    </a>
                  ),
                  code: ({ className, children, ...props }) => {
                    const isBlock = className?.includes("language-");
                    if (isBlock) {
                      return (
                        <pre
                          className="overflow-x-auto p-3 sm:p-4 my-4 text-xs"
                          style={{
                            backgroundColor: "var(--if-bg)",
                            borderLeft: "2px solid var(--if-accent)",
                            fontFamily: "var(--if-font-mono)",
                          }}
                        >
                          <code>{children}</code>
                        </pre>
                      );
                    }
                    return (
                      <code
                        className="px-1 py-0.5 text-xs"
                        style={{
                          backgroundColor: "var(--if-bg-surface)",
                          color: "var(--if-accent)",
                          fontFamily: "var(--if-font-mono)",
                        }}
                        {...props}
                      >
                        {children}
                      </code>
                    );
                  },
                  blockquote: ({ children }) => (
                    <blockquote
                      className="pl-4 my-4 text-sm"
                      style={{
                        borderLeft: "2px solid var(--if-accent)",
                        color: "var(--if-text-tertiary)",
                      }}
                    >
                      {children}
                    </blockquote>
                  ),
                  ul: ({ children }) => (
                    <ul className="list-disc pl-5 space-y-1.5 my-3 text-sm">{children}</ul>
                  ),
                  ol: ({ children }) => (
                    <ol className="list-decimal pl-5 space-y-1.5 my-3 text-sm">{children}</ol>
                  ),
                  li: ({ children }) => (
                    <li className="leading-relaxed" style={{ color: "var(--if-text-secondary)" }}>
                      {children}
                    </li>
                  ),
                  table: ({ children }) => (
                    <div className="overflow-x-auto my-4 -mx-4 sm:mx-0">
                      <table
                        className="w-full text-xs border-collapse min-w-[400px]"
                        style={{ borderColor: "var(--if-border)" }}
                      >
                        {children}
                      </table>
                    </div>
                  ),
                  th: ({ children }) => (
                    <th
                      className="border px-2 sm:px-3 py-2 text-left text-xs font-medium"
                      style={{
                        borderColor: "var(--if-border)",
                        backgroundColor: "var(--if-bg-surface)",
                        color: "var(--if-text)",
                      }}
                    >
                      {children}
                    </th>
                  ),
                  td: ({ children }) => (
                    <td
                      className="border px-2 sm:px-3 py-2 text-xs"
                      style={{ borderColor: "var(--if-border)", color: "var(--if-text-secondary)" }}
                    >
                      {children}
                    </td>
                  ),
                }}
              >
                {report.content}
              </ReactMarkdown>
            </article>
          </div>

          {/* Mobile-only sidebar content (collapsed by default) */}
          {hasSideContent && (
            <div className="xl:hidden space-y-3">
              {/* Info card — always visible on mobile */}
              <div
                className="border p-4"
                style={{
                  backgroundColor: "var(--if-bg-elevated)",
                  borderColor: "var(--if-border)",
                }}
              >
                <h3
                  className="text-xs uppercase tracking-widest mb-3"
                  style={{ color: "var(--if-text-tertiary)" }}
                >
                  報告資訊
                </h3>
                <div className="space-y-2.5 text-sm">
                  <div>
                    <span className="text-xs" style={{ color: "var(--if-text-dim)" }}>
                      原始查詢
                    </span>
                    <p className="mt-0.5 text-sm" style={{ color: "var(--if-text-secondary)" }}>
                      {report.query || "—"}
                    </p>
                  </div>
                  <div>
                    <span className="text-xs" style={{ color: "var(--if-text-dim)" }}>
                      建立日期
                    </span>
                    <p className="mt-0.5 text-sm" style={{ color: "var(--if-text-secondary)" }}>
                      {date}
                    </p>
                  </div>
                </div>
              </div>

              {report.sources && report.sources.length > 0 && (
                <SideSection
                  title="參考來源"
                  icon={<ExternalLink size={12} />}
                >
                  <div className="space-y-2">
                    {report.sources.map((src, i) => (
                      <a
                        key={i}
                        href={src.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block text-xs leading-snug"
                        style={{ color: "var(--if-accent)" }}
                      >
                        {src.title || src.url}
                      </a>
                    ))}
                  </div>
                </SideSection>
              )}

              {report.tags.length > 0 && (
                <SideSection title="標籤" icon={<Tag size={12} />}>
                  <div className="flex flex-wrap gap-2">
                    {report.tags.map((tag) => (
                      <TagBadge key={tag} tag={tag} />
                    ))}
                  </div>
                </SideSection>
              )}

              {report.topics && report.topics.length > 0 && (
                <SideSection title="相關主題" icon={<BookOpen size={12} />}>
                  <div className="space-y-1">
                    {report.topics.map((topic) => (
                      <span
                        key={topic.id}
                        className="block text-xs"
                        style={{ color: "var(--if-text-secondary)" }}
                      >
                        {topic.display_name || topic.name}
                      </span>
                    ))}
                  </div>
                </SideSection>
              )}
            </div>
          )}
        </div>

        {/* Right sidebar — desktop only */}
        <div className="hidden xl:block xl:w-[300px] space-y-4 shrink-0">
          {/* Info card */}
          <div
            className="border p-5 space-y-4"
            style={{
              backgroundColor: "var(--if-bg-elevated)",
              borderColor: "var(--if-border)",
            }}
          >
            <h3
              className="text-xs uppercase tracking-widest"
              style={{ color: "var(--if-text-tertiary)" }}
            >
              報告資訊
            </h3>
            <div className="space-y-3 text-sm">
              <div>
                <span className="text-xs" style={{ color: "var(--if-text-dim)" }}>
                  原始查詢
                </span>
                <p className="mt-1" style={{ color: "var(--if-text-secondary)" }}>
                  {report.query || "—"}
                </p>
              </div>
              <div>
                <span className="text-xs" style={{ color: "var(--if-text-dim)" }}>
                  建立日期
                </span>
                <p className="mt-1" style={{ color: "var(--if-text-secondary)" }}>
                  {date}
                </p>
              </div>
            </div>
          </div>

          {/* Sources */}
          {report.sources && report.sources.length > 0 && (
            <div
              className="border p-5 space-y-3"
              style={{
                backgroundColor: "var(--if-bg-elevated)",
                borderColor: "var(--if-border)",
              }}
            >
              <h3
                className="text-xs uppercase tracking-widest flex items-center gap-2"
                style={{ color: "var(--if-text-tertiary)" }}
              >
                <ExternalLink size={12} />
                參考來源
              </h3>
              <div className="space-y-2">
                {report.sources.map((src, i) => (
                  <a
                    key={i}
                    href={src.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block text-xs truncate"
                    style={{ color: "var(--if-accent)" }}
                  >
                    {src.title || src.url}
                  </a>
                ))}
              </div>
            </div>
          )}

          {/* Tags */}
          {report.tags.length > 0 && (
            <div
              className="border p-5 space-y-3"
              style={{
                backgroundColor: "var(--if-bg-elevated)",
                borderColor: "var(--if-border)",
              }}
            >
              <h3
                className="text-xs uppercase tracking-widest flex items-center gap-2"
                style={{ color: "var(--if-text-tertiary)" }}
              >
                <Tag size={12} />
                標籤
              </h3>
              <div className="flex flex-wrap gap-2">
                {report.tags.map((tag) => (
                  <TagBadge key={tag} tag={tag} />
                ))}
              </div>
            </div>
          )}

          {/* Topics */}
          {report.topics && report.topics.length > 0 && (
            <div
              className="border p-5 space-y-3"
              style={{
                backgroundColor: "var(--if-bg-elevated)",
                borderColor: "var(--if-border)",
              }}
            >
              <h3
                className="text-xs uppercase tracking-widest flex items-center gap-2"
                style={{ color: "var(--if-text-tertiary)" }}
              >
                <BookOpen size={12} />
                相關主題
              </h3>
              <div className="space-y-1">
                {report.topics.map((topic) => (
                  <span
                    key={topic.id}
                    className="block text-xs"
                    style={{ color: "var(--if-text-secondary)" }}
                  >
                    {topic.display_name || topic.name}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
