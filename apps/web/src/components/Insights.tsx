import type { Insight } from "@/lib/api";

const TONE = {
  positive: { icon: "▲", label: "Positivo" },
  negative: { icon: "▼", label: "A vigilar" },
  neutral: { icon: "●", label: "Hallazgo" },
} as const;

/** Hallazgos en texto. El tono va con icono + etiqueta, nunca solo color. */
export function Insights({ insights }: { insights: Insight[] }) {
  if (insights.length === 0) return null;
  return (
    <section aria-labelledby="insights-title">
      <h2 id="insights-title" className="mb-3 font-semibold">
        Hallazgos
      </h2>
      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {insights.map((insight) => {
          const tone = TONE[insight.tone];
          return (
            <li
              key={`${insight.kind}-${insight.title}`}
              className="rounded-xl border border-line bg-surface p-4"
            >
              <p className="flex items-center gap-2 text-xs font-medium text-ink-2">
                <span aria-hidden>{tone.icon}</span>
                <span className="sr-only">{tone.label}:</span>
                {insight.title}
              </p>
              <p className="mt-1.5">{insight.text}</p>
              <p className="mt-2 text-xs text-muted">{insight.basis}</p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
