/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { url } from "@web/core/utils/urls";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { loadPDFJSAssets } from "@web/libs/pdfjs";
import { Dialog } from "@web/core/dialog/dialog";
import {
    Component,
    onWillStart,
    onWillUpdateProps,
    onMounted,
    onPatched,
    useRef,
    useState,
} from "@odoo/owl";

const WORKER_SRC = "/web/static/lib/pdfjs/build/pdf.worker.js";

/**
 * Render a PDF (from `src`) into `container` using the bundled pdf.js, which
 * has no toolbar/download button. With `firstPageOnly` only page 1 is drawn
 * (used for the small thumbnail); otherwise every page is stacked (modal).
 */
async function renderPdfInto(container, src, { scale = 1.5, firstPageOnly = false } = {}) {
    const pdfjsLib = globalThis.pdfjsLib || window.pdfjsLib;
    if (!pdfjsLib || !container) {
        return;
    }
    pdfjsLib.GlobalWorkerOptions.workerSrc = WORKER_SRC;
    try {
        const pdf = await pdfjsLib.getDocument({ url: src }).promise;
        const lastPage = firstPageOnly ? 1 : pdf.numPages;
        for (let p = 1; p <= lastPage; p++) {
            const page = await pdf.getPage(p);
            const viewport = page.getViewport({ scale });
            const canvas = document.createElement("canvas");
            canvas.className = "o_secure_pdf_page";
            canvas.width = viewport.width;
            canvas.height = viewport.height;
            canvas.style.maxWidth = "100%";
            canvas.style.height = firstPageOnly ? "100%" : "auto";
            canvas.style.display = "block";
            canvas.style.marginBottom = firstPageOnly ? "0" : "8px";
            container.appendChild(canvas);
            await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
        }
    } catch {
        container.textContent = "Preview unavailable";
    }
}

/**
 * Full-size preview modal. Reuses the framework Dialog (close button + chrome).
 * Images render as <img>; PDFs render all pages onto canvas (no download path).
 */
export class SecurePreviewDialog extends Component {
    static template = "reema_sampling.SecurePreviewDialog";
    static components = { Dialog };
    static props = {
        item: Object,
        allowDownload: { type: Boolean, optional: true },
        close: { type: Function, optional: true },
    };

    setup() {
        this.body = useRef("body");
        onWillStart(() => loadPDFJSAssets());
        onMounted(() => {
            if (this.isPdf) {
                renderPdfInto(this.body.el, this.props.item.url, { scale: 1.5 });
            }
        });
    }

    get isImage() {
        const m = this.props.item.mimetype;
        return m && m.startsWith("image/");
    }

    get isPdf() {
        return this.props.item.mimetype === "application/pdf";
    }
}

/**
 * Read-only previewer for image / PDF attachments that deliberately exposes
 * NO download path. Renders small (~100px) thumbnails; clicking one opens a
 * modal with the full-size preview (SecurePreviewDialog). An explicit Download
 * button is shown only when configured with options="{'allow_download': True}".
 *
 * Supports two field types:
 *  - binary       (e.g. layout_file): single item; mimetype from sibling
 *                 helper field "<name>_mimetype".
 *  - many2many    (e.g. final_sample_images): one item per ir.attachment.
 */
export class SecureFilePreview extends Component {
    static template = "reema_sampling.SecureFilePreview";
    static props = {
        ...standardFieldProps,
        allowDownload: { type: Boolean, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.root = useRef("root");
        this.state = useState({ items: [] });

        onWillStart(async () => {
            await loadPDFJSAssets();
            this.state.items = await this.computeItems(this.props);
        });
        onWillUpdateProps(async (nextProps) => {
            this.state.items = await this.computeItems(nextProps);
        });
        onMounted(() => this.renderPdfThumbs());
        onPatched(() => this.renderPdfThumbs());
    }

    get fieldType() {
        return this.props.record.fields[this.props.name].type;
    }

    isImage(item) {
        return item.mimetype && item.mimetype.startsWith("image/");
    }

    isPdf(item) {
        return item.mimetype === "application/pdf";
    }

    openPreview(item) {
        this.dialog.add(SecurePreviewDialog, {
            item,
            allowDownload: this.props.allowDownload,
        });
    }

    /** Build [{url, downloadUrl, mimetype, name}] for the current record/field. */
    async computeItems(props) {
        const record = props.record;
        const fieldName = props.name;
        if (this.fieldType === "binary") {
            if (!record.data[fieldName] || !record.resId) {
                return [];
            }
            return [
                {
                    url: url("/web/content", {
                        model: record.resModel,
                        id: record.resId,
                        field: fieldName,
                    }),
                    downloadUrl: url("/web/content", {
                        model: record.resModel,
                        id: record.resId,
                        field: fieldName,
                        download: "true",
                    }),
                    mimetype: record.data[`${fieldName}_mimetype`] || "",
                    name: record.data[`${fieldName}_filename`] || "file",
                },
            ];
        }
        // many2many -> ir.attachment ids
        const value = record.data[fieldName];
        const ids = (value && value.records ? value.records : [])
            .map((r) => r.resId)
            .filter((id) => typeof id === "number");
        if (!ids.length) {
            return [];
        }
        const atts = await this.orm.read("ir.attachment", ids, ["name", "mimetype"]);
        return atts.map((a) => ({
            url: url(`/web/content/${a.id}`),
            downloadUrl: url(`/web/content/${a.id}`, { download: "true" }),
            mimetype: a.mimetype || "",
            name: a.name || "file",
        }));
    }

    /** Render the small first-page thumbnail for each PDF item. */
    async renderPdfThumbs() {
        if (!this.root.el) {
            return;
        }
        const containers = this.root.el.querySelectorAll(
            ".o_secure_pdf_thumb:not([data-rendered])"
        );
        for (const container of containers) {
            container.dataset.rendered = "1";
            await renderPdfInto(container, container.dataset.url, {
                scale: 0.4,
                firstPageOnly: true,
            });
        }
    }
}

export const secureFilePreview = {
    component: SecureFilePreview,
    supportedTypes: ["binary", "many2many"],
    extractProps: ({ options }) => ({
        allowDownload: !!(options && options.allow_download),
    }),
};

registry.category("fields").add("secure_file_preview", secureFilePreview);
