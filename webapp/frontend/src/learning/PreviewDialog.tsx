import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

/** The native dialog provides focus trapping, Escape and background isolation. */
export default function PreviewDialog({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
    return () => {
      if (dialog?.open) dialog.close();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={`v2-dialog${wide ? " v2-dialog--wide" : ""}`}
      aria-label={title}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      <div className="v2-dialog__head">
        <h2>{title}</h2>
        <button
          className="v2-icon-button"
          type="button"
          onClick={onClose}
          aria-label="Close dialog"
        >
          <X size={20} />
        </button>
      </div>
      <p className="v2-dialog__preview-note">
        Illustrative programme · Sample pricing and CPD information
      </p>
      {children}
    </dialog>
  );
}
