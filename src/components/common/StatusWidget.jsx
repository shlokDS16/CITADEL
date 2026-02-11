import ProgressBar from './ProgressBar';

export default function StatusWidget() {
  return (
    <div className="bg-white dark:bg-black border-4 border-black dark:border-white p-4 neo-shadow">
      <div className="mb-4 pb-2 border-b-2 border-black dark:border-white">
        <h3 className="text-xs font-black tight-caps">CORE_DYNAMICS</h3>
      </div>

      <ProgressBar label="Neural Processing" percentage={94} color="cyan" />
      <ProgressBar label="Quantum Storage" percentage={22} color="purple" />
      <ProgressBar label="Grid Stability" percentage={100} color="green" />

      <div className="mt-4 pt-4 border-t-2 border-black dark:border-white">
        <div className="flex items-center justify-between text-xs">
          <span className="font-black tight-caps">System Status</span>
          <span className="font-bold text-terminal-green">OPTIMAL</span>
        </div>
      </div>
    </div>
  );
}
