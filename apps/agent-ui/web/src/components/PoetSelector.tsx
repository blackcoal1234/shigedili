import { Search } from "lucide-react";
import { useMemo, useState } from "react";

import type { PoetCatalogRow } from "@/lib/types";

interface PoetSelectorProps {
  poets: PoetCatalogRow[];
  selectedPoet: string;
  onSelect: (poet: string) => void;
}

export function PoetSelector({ poets, selectedPoet, onSelect }: PoetSelectorProps) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const normalized = query.trim();
    return normalized ? poets.filter((row) => row.poet.includes(normalized)) : poets;
  }, [poets, query]);

  return (
    <div className="poet-selector">
      <div className="section-heading compact-heading">
        <div>
          <span>诗人目录</span>
          <strong>{poets.length}</strong>
        </div>
        <small>{filtered.length} 位可见</small>
      </div>

      <label className="search-field">
        <Search size={15} aria-hidden="true" />
        <span className="sr-only">检索诗人</span>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="检索诗人"
        />
      </label>

      <label className="mobile-poet-select">
        <span className="sr-only">选择诗人</span>
        <select value={selectedPoet} onChange={(event) => onSelect(event.target.value)}>
          {poets.map((row) => (
            <option value={row.poet} key={row.poet}>
              {row.dynasty} · {row.poet} · {row.workCount} 篇
            </option>
          ))}
        </select>
      </label>

      <div className="poet-list" role="listbox" aria-label="88 位诗人">
        {filtered.map((row) => {
          const active = row.poet === selectedPoet;
          return (
            <button
              type="button"
              role="option"
              aria-selected={active}
              className="poet-row"
              data-active={active}
              onClick={() => onSelect(row.poet)}
              key={row.poet}
            >
              <span className="poet-name">
                <strong>{row.poet}</strong>
                <small>{row.dynasty} · {row.workCount} 篇</small>
              </span>
              <span
                className="route-dot"
                data-status={row.routeStatus}
                title={row.routeStatus === "available" ? `${row.sceneCount} 个镜头` : "证据不足"}
              />
            </button>
          );
        })}
        {filtered.length === 0 ? <p className="no-poets">未找到匹配诗人</p> : null}
      </div>
    </div>
  );
}
