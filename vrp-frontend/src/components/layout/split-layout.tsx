import { useRef } from "react";

export function SplitLayout({
  left,
  right,
  showRight,
  rightWidth,
  setRightWidth,
}: {
  left: React.ReactNode;
  right: React.ReactNode;
  showRight: boolean;
  rightWidth: number;
  setRightWidth: (width: number) => void;
}) {
  const dragging = useRef(false);

  const startDrag = () => {
    dragging.current = true;
    const onMove = (event: MouseEvent) => {
      if (!dragging.current) return;
      const viewportWidth = window.innerWidth;
      const nextWidth = Math.min(520, Math.max(280, viewportWidth - event.clientX - 24));
      setRightWidth(nextWidth);
    };
    const onUp = () => {
      dragging.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  return (
    <div className="flex min-h-[calc(100vh-14rem)] gap-4">
      <div className="min-w-0 flex-1">{left}</div>
      {showRight && (
        <>
          <div
            onMouseDown={startDrag}
            className="hidden w-2 shrink-0 cursor-col-resize rounded-full bg-white/5 transition hover:bg-accent/30 xl:block"
          />
          <div className="hidden shrink-0 xl:block" style={{ width: rightWidth }}>
            {right}
          </div>
        </>
      )}
    </div>
  );
}
