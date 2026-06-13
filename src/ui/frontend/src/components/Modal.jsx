import { X } from "lucide-react";

import IconButton from "./IconButton.jsx";

export default function Modal({ title, children, footer, onClose }) {
  return (
    <div className="modal-layer" role="presentation" onMouseDown={onClose}>
      <section className="modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <header className="modal-header">
          <h2>{title}</h2>
          <IconButton icon={X} label="" aria-label="Close" onClick={onClose} />
        </header>
        <div className="modal-body">{children}</div>
        {footer ? <footer className="modal-footer">{footer}</footer> : null}
      </section>
    </div>
  );
}
