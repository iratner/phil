import styles from "./hrefButton.module.css";

interface HrefButtonProps {
  variant?: "primary" | "secondary";
}

export const HrefButton = ({
  variant = "primary",
  children,
  ...props
}: React.ComponentPropsWithoutRef<"a"> & HrefButtonProps) => {
  return (
    <a
      {...props}
      className={variant === "primary" ? styles.primary : styles.secondary}
    >
      {children}
    </a>
  );
};
