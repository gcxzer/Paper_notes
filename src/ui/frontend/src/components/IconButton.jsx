export default function IconButton({
  icon: Icon,
  label,
  active = false,
  variant = "default",
  className = "",
  ...props
}) {
  return (
    <button
      className={[
        "icon-button",
        `icon-button-${variant}`,
        active ? "is-active" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      type="button"
      aria-label={props["aria-label"] || label}
      title={props.title || label}
      {...props}
    >
      {Icon ? <Icon size={17} strokeWidth={1.9} aria-hidden="true" /> : null}
      {label ? <span>{label}</span> : null}
    </button>
  );
}
