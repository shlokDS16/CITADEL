import { useNavigate } from 'react-router-dom';

export default function ModuleCard({
  title,
  gateway,
  icon,
  color = 'primary',
  status = 'INITIALIZING...',
  subtitle = '',
  path,
  tiltDirection = 'left',
}) {
  const navigate = useNavigate();

  const colorMap = {
    primary: {
      bg: 'bg-primary',
      shadow: 'neo-shadow',
      hoverCollapse: 'hover-collapse',
    },
    pink: {
      bg: 'bg-accent-pink',
      shadow: 'neo-shadow-pink',
      hoverCollapse: 'hover-collapse-pink',
    },
    cyan: {
      bg: 'bg-accent-cyan',
      shadow: 'neo-shadow-cyan',
      hoverCollapse: 'hover-collapse-cyan',
    },
    purple: {
      bg: 'bg-accent-purple',
      shadow: 'neo-shadow-purple',
      hoverCollapse: 'hover-collapse',
    },
  };

  const tiltClass = tiltDirection === 'left' ? 'tilted-card-left' : 'tilted-card-right';
  const colors = colorMap[color];

  return (
    <div
      onClick={() => path && navigate(path)}
      className={`
        relative bg-white dark:bg-gray-900 border-4 border-black
        ${colors.shadow} ${colors.hoverCollapse} ${tiltClass} hover-tilt-reduce
        cursor-pointer transition-all duration-300 overflow-hidden
      `}
    >
      {/* Gateway badge */}
      <div className="absolute top-4 right-4 z-10">
        <div className={`px-3 py-1 ${colors.bg} border-2 border-black`}>
          <span className="text-xs font-black tight-caps text-black">{gateway}</span>
        </div>
      </div>

      {/* Colored header */}
      <div className={`${colors.bg} px-6 py-4 border-b-4 border-black skewed-header`}>
        <h3 className="text-lg font-black tight-caps text-black">{title}</h3>
      </div>

      {/* Content */}
      <div className="p-8 flex flex-col items-center justify-center min-h-[280px]">
        {/* Icon */}
        {icon && (
          <div className="mb-6 text-6xl">
            {typeof icon === 'string' ? (
              <span className="material-symbols-outlined" style={{ fontSize: '4rem' }}>
                {icon}
              </span>
            ) : (
              icon
            )}
          </div>
        )}

        {/* Status */}
        <div className="text-center">
          <div className="text-sm font-black tight-caps mb-2">{status}</div>
          {subtitle && (
            <div className="text-xs text-gray-600 dark:text-gray-400 uppercase font-mono">
              {subtitle}
            </div>
          )}
        </div>
      </div>

      {/* Bottom accent line */}
      <div className={`h-2 ${colors.bg}`} />
    </div>
  );
}
