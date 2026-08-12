import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** What failed, shown to the user. Name the feature, not the component. */
  label: string;
}

interface State {
  message: string | null;
}

/**
 * Contains a render failure to one part of the screen.
 *
 * React unmounts the entire tree when a render throws and nothing catches it,
 * so a defect in a subordinate panel takes the whole dashboard with it and the
 * user sees a blank page with no indication of why. That is exactly what
 * happened: the off-screen print report read a field absent from results saved
 * by an older engine build, and the dashboard went black.
 *
 * The failure is reported rather than swallowed. A boundary that renders
 * nothing at all is only a quieter version of the same problem.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { message: null };

  static getDerivedStateFromError(error: unknown): State {
    return { message: error instanceof Error ? error.message : String(error) };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Kept on the console: this is a real defect, and a boundary that hides it
    // trades a blank screen for a silent one.
    console.error(`[${this.props.label}] render failed`, error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.message !== null) {
      return (
        <div className="rk-boundary" role="alert">
          {this.props.label} could not be rendered — {this.state.message}. The rest of the
          dashboard is unaffected.
        </div>
      );
    }
    return this.props.children;
  }
}
