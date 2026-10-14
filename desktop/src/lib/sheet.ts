import { toPng } from "html-to-image";
import { useLayoutEffect, useState, type RefObject } from "react";
import { isTauri } from "./files";

export const SHEET_WIDTH = 1600;

/** Scale of a fixed-width report sheet so it fits the frame on screen; the export is always full size. */
export function useFitScale(frame: RefObject<HTMLDivElement>, ready: unknown): number {
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    const fit = () => frame.current && setScale(Math.min(1, frame.current.clientWidth / SHEET_WIDTH));
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [frame, ready]);
  return scale;
}

/** Renders a report sheet to PNG and saves it: native save dialog in the desktop app, download in a browser.
 * Returns false when the person cancelled the save dialog. */
export async function exportSheetPng(node: HTMLElement, filename: string): Promise<boolean> {
  await document.fonts.ready;
  const url = await toPng(node, { pixelRatio: 2, cacheBust: true, backgroundColor: "#ffffff" });
  if (isTauri()) {
    const { save } = await import("@tauri-apps/plugin-dialog");
    const { writeFile } = await import("@tauri-apps/plugin-fs");
    const path = await save({ defaultPath: filename, filters: [{ name: "Imagem PNG", extensions: ["png"] }] });
    if (!path) return false;
    const bytes = Uint8Array.from(atob(url.split(",")[1]), (c) => c.charCodeAt(0));
    await writeFile(path, bytes);
    return true;
  }
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  return true;
}
