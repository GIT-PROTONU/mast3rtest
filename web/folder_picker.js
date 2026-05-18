import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const IMAGE_EXTS = /\.(png|jpe?g|webp|bmp)$/i;

async function uploadAll(files, subfolder, onProgress) {
    let ok = 0;
    let fail = 0;
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const fd = new FormData();
        fd.append("image", file, file.name);
        fd.append("type", "input");
        fd.append("subfolder", subfolder);
        fd.append("overwrite", "true");
        try {
            const resp = await api.fetchApi("/upload/image", { method: "POST", body: fd });
            if (resp.status === 200) ok++;
            else fail++;
        } catch (err) {
            console.error("[Mast3rFolderInput] upload error", err);
            fail++;
        }
        onProgress(i + 1, files.length, ok, fail);
    }
    return { ok, fail };
}

app.registerExtension({
    name: "mast3r.folderpicker",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "Mast3rFolderInput") return;

        const onCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onCreated?.apply(this, arguments);
            if (this._fpWired) return r;
            this._fpWired = true;

            const subfolderWidget = this.widgets?.find((w) => w.name === "subfolder");
            if (!subfolderWidget) return r;

            const fileInput = document.createElement("input");
            fileInput.type = "file";
            fileInput.multiple = true;
            try {
                fileInput.webkitdirectory = true;
                fileInput.directory = true;
                fileInput.setAttribute("webkitdirectory", "");
            } catch (e) { /* not supported */ }
            fileInput.style.display = "none";
            document.body.appendChild(fileInput);

            const status = this.addWidget(
                "text",
                "status",
                "(no folder picked)",
                () => {},
                { serialize: false }
            );

            this.addWidget("button", "Pick Folder", "", () => {
                fileInput.value = "";
                fileInput.click();
            });

            this.addWidget("button", "Pick Files", "", () => {
                fileInput.value = "";
                fileInput.removeAttribute("webkitdirectory");
                fileInput.click();
                setTimeout(() => fileInput.setAttribute("webkitdirectory", ""), 0);
            });

            fileInput.onchange = async (e) => {
                const all = Array.from(e.target.files || []);
                const images = all.filter((f) => IMAGE_EXTS.test(f.name));
                if (images.length === 0) {
                    status.value = "no .png/.jpg/.jpeg/.webp/.bmp files in that selection";
                    this.setDirtyCanvas?.(true, true);
                    return;
                }

                const sub = `mast3r_${Date.now()}`;
                subfolderWidget.value = sub;
                status.value = `uploading 0/${images.length}...`;
                this.setDirtyCanvas?.(true, true);

                const { ok, fail } = await uploadAll(images, sub, (i, total, k, f) => {
                    status.value = `uploading ${i}/${total}  (ok=${k} fail=${f})`;
                    this.setDirtyCanvas?.(true, true);
                });

                status.value =
                    `${ok} image(s) ready in input/${sub}/` +
                    (fail ? `  (${fail} failed)` : "");
                this.setDirtyCanvas?.(true, true);
            };
        };
    },
});
