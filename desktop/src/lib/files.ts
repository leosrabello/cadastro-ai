// Native file picker inside Tauri; a plain <input type=file> when running in a browser (dev).

export interface PickedFile {
  name: string;
  size: number;
  read: () => Promise<Blob>;
}

const ACCEPT = ["pdf", "jpg", "jpeg", "png", "docx", "doc", "xlsx", "xls"];
const MIME: Record<string, string> = {
  pdf: "application/pdf", jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", doc: "application/msword",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", xls: "application/vnd.ms-excel",
};

export const isTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export function fromBrowserFiles(list: FileList | File[]): PickedFile[] {
  return Array.from(list).map((f) => ({ name: f.name, size: f.size, read: async () => f }));
}

export async function pickFiles(): Promise<PickedFile[]> {
  if (isTauri()) {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const { readFile, stat } = await import("@tauri-apps/plugin-fs");
    const selected = await open({ multiple: true, directory: false, filters: [{ name: "Documentos", extensions: ACCEPT }] });
    const paths = selected === null ? [] : Array.isArray(selected) ? selected : [selected];
    return Promise.all(
      paths.map(async (path) => {
        const name = path.split(/[\\/]/).pop() ?? "documento";
        const ext = name.split(".").pop()?.toLowerCase() ?? "";
        const info = await stat(path);
        return {
          name,
          size: info.size,
          read: async () => new Blob([await readFile(path)], { type: MIME[ext] ?? "application/octet-stream" }),
        };
      }),
    );
  }
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.accept = ACCEPT.map((e) => "." + e).join(",");
    input.onchange = () => resolve(input.files ? fromBrowserFiles(input.files) : []);
    input.click();
  });
}
