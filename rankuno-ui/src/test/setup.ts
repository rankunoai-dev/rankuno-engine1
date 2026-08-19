/**
 * Global setup for component tests.
 *
 * jsdom implements enough of a browser to mount React, and stops well short of
 * a real one. Everything polyfilled here is something antd calls during render
 * and jsdom does not provide — each one crashed a component before it was
 * added, so none of them is precautionary.
 */

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

/*
 * Unmount between tests, then sweep up what antd leaves behind.
 *
 * Two separate problems, and the order matters.
 *
 * `cleanup` unmounts the React trees RTL created. Without it every test appends
 * another copy of the component to the same document and an unambiguous
 * `getByText` starts failing with "found multiple elements" in whichever test
 * happens to run second.
 *
 * antd Modals then portal their content into a `div` appended to
 * `document.body`, outside RTL's container. React removes its own nodes on
 * unmount but the empty wrapper can survive, and a stale wrapper is what makes
 * a suite pass alone and fail together.
 *
 * The sweep runs *after* `cleanup`, in the same hook rather than a second one:
 * Vitest runs `afterEach` hooks last-registered-first, so a separate hook would
 * have torn the DOM out from under React and failed the unmount with "the node
 * to be removed is not a child of this node" — which it did, on all nine tests,
 * before this was written as one hook.
 *
 * The node itself is removed, never its parent: the modal root and its wrap are
 * nested, and removing a parent invalidates the sibling still to be swept.
 */
afterEach(() => {
  cleanup();
  document
    .querySelectorAll(".ant-modal-root, .ant-modal-wrap")
    .forEach((node) => node.remove());
});

/*
 * antd reads `matchMedia` on mount for its responsive grid and for
 * `prefers-reduced-motion`. jsdom has no implementation at all, so the call is
 * a TypeError and the component never renders — which looks like a bug in the
 * component rather than a missing browser API.
 */
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }),
});

/*
 * `ResizeObserver` is used by antd's Table and by `FocusGraphStage`'s measure
 * pass. jsdom does not implement it. The stub reports nothing rather than
 * faking a size: a component that needs real geometry should be tested for
 * behaviour it can have in jsdom, not handed invented pixel values that make an
 * assertion pass for the wrong reason.
 */
class NoopResizeObserver implements ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
window.ResizeObserver = NoopResizeObserver;

/*
 * `scrollTo` is called by the virtualized tree when it teleports to a node.
 * jsdom defines the property but throws "not implemented" from it, which fails
 * a test for a reason that has nothing to do with the code under test.
 */
window.HTMLElement.prototype.scrollTo = (): void => {};

/*
 * `Blob.prototype.text` is not implemented by jsdom at all — `typeof
 * file.text` is `undefined`, so `ReconcilePanel` throws the moment a file is
 * chosen. The method is standard and every target browser has it; this is an
 * environment gap, not a component defect, which is exactly what a polyfill is
 * for.
 *
 * Built on `FileReader`, which jsdom *does* implement, rather than returning a
 * canned string: a stub that ignored the blob would let a test pass while the
 * component read the wrong file.
 */
if (typeof Blob.prototype.text !== "function") {
  Blob.prototype.text = function readAsText(this: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(this);
    });
  };
}
