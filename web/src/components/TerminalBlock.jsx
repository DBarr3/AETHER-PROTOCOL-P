import React from "react";

const kindClass = {
  prompt: "text-aether-cyan",
  log: "text-aether-dim",
  ok: "text-aether-green",
  warn: "text-aether-gold",
  err: "text-aether-red",
};

const prefixFor = (kind) => {
  if (kind === "prompt") return "$";
  return " ";
};

export default function TerminalBlock({ title = "aetherctl", lines = [] }) {
  return (
    <div className="aether-terminal relative w-full overflow-hidden">
      <div className="flex items-center justify-between border-b border-aether-border px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-aether-red/80" />
          <span className="h-2.5 w-2.5 rounded-full bg-aether-gold/80" />
          <span className="h-2.5 w-2.5 rounded-full bg-aether-green/80" />
        </div>
        <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-aether-muted">
          {title}
        </div>
      </div>
      <pre className="m-0 max-h-[440px] overflow-auto px-5 py-5 text-[12.5px] leading-[1.85]">
        {lines.map((line, i) => (
          <div
            key={i}
            className={`flex gap-3 ${kindClass[line.kind] || "text-aether-dim"}`}
          >
            <span className="select-none text-aether-muted">
              {prefixFor(line.kind)}
            </span>
            <span>{line.text}</span>
          </div>
        ))}
        <div className="mt-2 flex gap-3">
          <span className="text-aether-muted">$</span>
          <span className="inline-block h-[14px] w-[8px] animate-pulse bg-aether-cyan" />
        </div>
      </pre>
    </div>
  );
}
