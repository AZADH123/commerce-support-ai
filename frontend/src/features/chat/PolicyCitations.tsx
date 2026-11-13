import type { PolicyCitation } from "../../api/types";

export function PolicyCitations({ citations }: { citations: PolicyCitation[] }) {
  if (!citations || citations.length === 0) return null;
  return (
    <ul className="citations" aria-label="Policy citations">
      {citations.map((citation) => (
        <li
          key={`${citation.document_id}-${citation.version}-${citation.chunk_index}`}
          className="citation"
        >
          <span className="citation-title">
            {citation.title} · v{citation.version}
          </span>
          <span className="citation-source">{citation.source}</span>
          <span className="citation-snippet">{citation.snippet}</span>
        </li>
      ))}
    </ul>
  );
}
