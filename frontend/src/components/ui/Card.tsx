import type { ReactNode } from "react";

interface CardProps {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  labelledBy?: string;
}

export function Card({ title, description, actions, children, className, labelledBy }: CardProps) {
  return (
    <section className={`card ${className ?? ""}`} aria-labelledby={labelledBy}>
      {(title || actions) && (
        <div className="card__head">
          <div>
            {title && (
              <h2 className="card__title" id={labelledBy}>
                {title}
              </h2>
            )}
            {description && <p className="card__desc">{description}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}
