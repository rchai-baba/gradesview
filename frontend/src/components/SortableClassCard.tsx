import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

interface Props {
  id: string;
  children: React.ReactNode;
  className?: string;
  onNavigate: () => void;
}

/**
 * GradesHome uses PointerSensor distance (not delay): small move starts drag; tap without move navigates.
 */
export function SortableClassCard({ id, children, className = "", onNavigate }: Props) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition: isDragging ? "transform 180ms cubic-bezier(0.32, 0.72, 0, 1)" : transition,
    opacity: isDragging ? 0.2 : 1,
    zIndex: isDragging ? 1 : 0,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`rounded-xl border border-border bg-card p-6 hover:shadow-md flex flex-col items-center justify-center min-h-[140px] select-none touch-manipulation transition-[box-shadow,opacity,transform] duration-200 ease-out ${
        isDragging ? "ring-2 ring-primary/40 scale-[0.98]" : ""
      } ${className}`}
      {...attributes}
      {...listeners}
      onClick={onNavigate}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onNavigate();
        }
      }}
    >
      {children}
    </div>
  );
}
