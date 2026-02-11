export default function ProgressBar({ label, percentage, color = 'primary' }) {
  const colorMap = {
    primary: 'bg-primary',
    cyan: 'bg-accent-cyan',
    pink: 'bg-accent-pink',
    purple: 'bg-accent-purple',
    green: 'bg-terminal-green',
  };

  return (
    <div className="mb-4">
      <div className="flex justify-between items-center mb-2">
        <span className="text-xs font-black tight-caps">{label}</span>
        <span className="text-xs font-bold font-mono">{percentage}%</span>
      </div>
      <div className="h-3 w-full bg-black/10 dark:bg-white/10 border-2 border-black overflow-hidden relative">
        <div
          className={`h-full ${colorMap[color]} transition-all duration-500`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}
