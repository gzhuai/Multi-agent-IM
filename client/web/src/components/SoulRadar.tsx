// SVG six-axis radar chart for Soul Profile visualization
interface SoulData {
  openness: number;
  conscientiousness: number;
  extraversion: number;
  agreeableness: number;
  neuroticism: number;
  directness?: number;
}

export function SoulRadar({ traits, size = 200 }: { traits: SoulData; size?: number }) {
  const cx = size / 2;
  const cy = size / 2;
  const r = size * 0.38;
  const levels = [0.2, 0.4, 0.6, 0.8, 1.0];

  const dimensions = [
    { key: "openness", label: "开放性", value: traits.openness },
    { key: "conscientiousness", label: "尽责性", value: traits.conscientiousness },
    { key: "extraversion", label: "外向性", value: traits.extraversion },
    { key: "agreeableness", label: "宜人性", value: traits.agreeableness },
    { key: "neuroticism", label: "情绪敏感", value: traits.neuroticism },
    { key: "directness", label: "直接度", value: traits.directness ?? 0.5 },
  ];

  const angle = (index: number) => (Math.PI * 2 * index) / dimensions.length - Math.PI / 2;
  const point = (index: number, value: number) => {
    const a = angle(index);
    return { x: cx + r * value * Math.cos(a), y: cy + r * value * Math.sin(a) };
  };

  // Data polygon
  const dataPoints = dimensions
    .map((d, i) => point(i, d.value))
    .map((p) => `${p.x},${p.y}`)
    .join(" ");

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="mx-auto">
      {/* Level rings */}
      {levels.map((level) => (
        <polygon
          key={level}
          points={dimensions
            .map((_, i) => point(i, level))
            .map((p) => `${p.x},${p.y}`)
            .join(" ")}
          fill="none"
          stroke="rgba(255,255,255,0.08)"
          strokeWidth="0.5"
        />
      ))}

      {/* Axis lines */}
      {dimensions.map((_, i) => {
        const p = point(i, 1);
        return (
          <line
            key={i}
            x1={cx}
            y1={cy}
            x2={p.x}
            y2={p.y}
            stroke="rgba(255,255,255,0.1)"
            strokeWidth="0.5"
          />
        );
      })}

      {/* Data area */}
      <polygon
        points={dataPoints}
        fill="rgba(99,102,241,0.3)"
        stroke="rgba(99,102,241,0.8)"
        strokeWidth="2"
      />

      {/* Data points */}
      {dimensions.map((d, i) => {
        const p = point(i, d.value);
        return (
          <circle key={i} cx={p.x} cy={p.y} r="4" fill="#818cf8" stroke="#fff" strokeWidth="1.5" />
        );
      })}

      {/* Labels */}
      {dimensions.map((d, i) => {
        const p = point(i, 1.25);
        return (
          <text
            key={i}
            x={p.x}
            y={p.y}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="rgba(255,255,255,0.5)"
            fontSize="11"
            fontWeight="500"
          >
            {d.label}
          </text>
        );
      })}
    </svg>
  );
}
