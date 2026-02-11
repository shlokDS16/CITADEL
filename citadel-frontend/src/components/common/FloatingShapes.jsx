export default function FloatingShapes() {
  return (
    <div className="fixed inset-0 pointer-events-none overflow-hidden z-0">
      <div
        className="absolute top-20 left-1/4 w-24 h-24 bg-primary border-4 border-black neo-shadow floating"
        style={{ borderRadius: '20% 80% 20% 80%' }}
      />
      <div
        className="absolute bottom-20 right-1/4 w-32 h-32 bg-accent-pink border-4 border-black neo-shadow-sm floating floating-delay-1"
        style={{ borderRadius: '50%' }}
      />
      <div
        className="absolute top-1/3 right-10 w-16 h-16 bg-white border-4 border-black neo-shadow floating floating-delay-2"
        style={{ transform: 'rotate(45deg)' }}
      />
      <div
        className="absolute bottom-1/3 left-10 w-20 h-20 bg-black dark:bg-primary border-4 border-white neo-shadow-sm floating floating-delay-3"
      />
      <div
        className="absolute top-2/3 left-1/3 w-12 h-12 bg-accent-cyan border-4 border-black neo-shadow-sm floating"
        style={{ borderRadius: '30%' }}
      />
      <div
        className="absolute bottom-1/4 right-1/3 w-28 h-28 bg-accent-purple border-4 border-black neo-shadow floating floating-delay-2"
        style={{ clipPath: 'polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)' }}
      />
    </div>
  );
}
