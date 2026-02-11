export default function TerminalDisplay({ lines = [], title = 'ENCRYPTED_COMMS' }) {
  return (
    <div className="bg-white dark:bg-black border-4 border-black dark:border-white p-4">
      <div className="mb-2 pb-2 border-b-2 border-black dark:border-white">
        <h3 className="text-xs font-black tight-caps">{title}</h3>
      </div>
      <div className="bg-black p-3 font-mono text-terminal-green text-xs overflow-hidden min-h-[120px] max-h-[200px] overflow-y-auto">
        {lines.length > 0 ? (
          lines.map((line, idx) => (
            <div key={idx} className="mb-1">
              <span className="text-primary mr-2">&gt;</span>
              {line}
            </div>
          ))
        ) : (
          <div className="text-gray-600">
            <span className="text-primary mr-2">&gt;</span>
            System idle...
          </div>
        )}
        <div className="animate-pulse">
          <span className="text-primary mr-2">&gt;</span>
          <span className="inline-block w-2 h-3 bg-terminal-green" />
        </div>
      </div>
    </div>
  );
}
