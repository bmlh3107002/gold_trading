import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  icon?: ReactNode;
}

export function Button({ variant = "secondary", icon, className, children, ...rest }: ButtonProps) {
  return (
    <button type="button" className={`btn btn--${variant} ${className ?? ""}`} {...rest}>
      {icon}
      {children}
    </button>
  );
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  tone?: "default" | "gold" | "danger";
}

export function IconButton({ label, tone = "default", className, children, ...rest }: IconButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={`icon-btn ${tone !== "default" ? `icon-btn--${tone}` : ""} ${className ?? ""}`}
      {...rest}
    >
      {children}
    </button>
  );
}
