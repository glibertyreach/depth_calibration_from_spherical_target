"use strict";
/**
 * Stage-1 capture overview deck generator.
 *
 * Reads  docs/presentations/build/stage1_deck_content.json  (single source of truth for all text)
 * and    docs/presentations/assets/*.png                    (figures)
 * writes docs/presentations/stage1_capture_overview.pptx
 *
 * Run from the repository root:
 *     NODE_PATH=<folder with node_modules for pptxgenjs, react-icons, react, react-dom, sharp> \
 *         node docs/presentations/build/make_stage1_deck.js
 *
 * Structure (see the pptx skill, "Structured decks"):
 *   - a named theme ("Stage-1 Capture") whose colors are written into the file by applyTheme();
 *   - every color is a theme (scheme) color, except inside rasterized icons (images need hex);
 *   - two layouts: TITLE_DARK and TITLE_ONLY, with named placeholders that slides fill by name;
 *   - one section per topic; speaker notes on every slide.
 *
 * All sizes are inches unless a name says "PT" (points). Nothing is hard-coded in the slide
 * builders: every dimension, font size, spacing and color comes from the constants below.
 */

const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");

// ---------------------------------------------------------------------------------------------
// File locations (relative to the repository root, which is the working directory)
// ---------------------------------------------------------------------------------------------
const PRESENTATIONS_DIR = path.join("docs", "presentations");
const CONTENT_JSON = path.join(PRESENTATIONS_DIR, "build", "stage1_deck_content.json");
const OUTPUT_PPTX = path.join(PRESENTATIONS_DIR, "stage1_capture_overview.pptx");
// Folder of the pptx skill's scripts; only apply_theme.js is used from it.
const SKILL_SCRIPTS_DIR =
	process.env.PPTX_SKILL_SCRIPTS ||
	"/root/.claude/skills/synced/f2fe48f6-69a7-4a19-a27a-2fac391c7f33_06dd8df9-d222-4305-b701-72191c02d7f8/pptx/scripts";
const { applyTheme } = require(path.join(SKILL_SCRIPTS_DIR, "apply_theme.js"));

// ---------------------------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------------------------
const THEME = {
	name: "Stage-1 Capture",
	headFontFace: "Cambria", // headings
	bodyFontFace: "Calibri", // everything else
	colors: {
		dk1: "1F2A30", // graphite text
		lt1: "FFFFFF", // white
		dk2: "2E4A52", // deep steel teal: dark slides, headings
		lt2: "EEF2F3", // cool light gray tint: cards
		accent1: "D9731A", // safety orange: step badges, stat numbers, key message
		accent2: "3E7C87", // steel teal: icons, secondary
		accent3: "8FA9AE", // soft steel
		accent4: "B23A2E", // signal red: warnings only
		accent5: "5B6B70", // muted caption gray
		accent6: "C9D6D8", // pale steel: outlines
		hlink: "3E7C87",
		folHlink: "5B6B70",
	},
};

// Theme font references, so that text follows the theme instead of naming a font.
const HEAD_FONT_REF = "+mj-lt"; // theme heading font (Cambria)
const MONO_FONT = "Courier New"; // the one explicitly named font: the pose-log example line

// ---------------------------------------------------------------------------------------------
// Page geometry
// ---------------------------------------------------------------------------------------------
const SLIDE_W = 13.333; // LAYOUT_WIDE width
const SLIDE_H = 7.5; // LAYOUT_WIDE height
const MARGIN = 0.5; // minimum distance from content to slide edge
const GAP = 0.3; // standard gap between blocks
const GAP_TIGHT = 0.2; // gap between items inside one list or column (rows of a list, icon to text)
const CONTENT_X = MARGIN; // left edge of content
const CONTENT_W = SLIDE_W - 2 * MARGIN; // width of content area

const TITLE_Y = MARGIN; // content-slide title: top
const TITLE_H = 0.75; // content-slide title: height (one line at TITLE_PT)
const CONTENT_TOP = TITLE_Y + TITLE_H + GAP; // first y available to content

const NUMBER_W = 0.6; // slide-number box width
const NUMBER_H = 0.3; // slide-number box height
const NUMBER_BOTTOM_GAP = 0.2; // distance of slide-number box from the slide's bottom edge
const NUMBER_Y = SLIDE_H - NUMBER_BOTTOM_GAP - NUMBER_H; // slide-number box top
const CONTENT_BOTTOM = NUMBER_Y - GAP; // last y available to content
const CONTENT_H = CONTENT_BOTTOM - CONTENT_TOP; // height available to content

// Dark layout: title top-left as on content slides but larger, then subtitle, footer at the bottom.
const DARK_TITLE_H = 0.95; // title placeholder height (one line at DARK_TITLE_PT)
const DARK_SUBTITLE_Y = MARGIN + DARK_TITLE_H + GAP_TIGHT; // subtitle top
const DARK_SUBTITLE_W = 9.0; // subtitle width (wraps to two lines)
const DARK_SUBTITLE_H = 0.9; // subtitle height
const DARK_FOOTER_H = 0.4; // footer placeholder height
const DARK_FOOTER_Y = SLIDE_H - MARGIN - DARK_FOOTER_H; // footer top
const DARK_CONTENT_TOP = MARGIN + DARK_TITLE_H + GAP; // first y of content on the closing slide
const DARK_CONTENT_H = SLIDE_H - MARGIN - DARK_CONTENT_TOP; // closing-slide content height (no slide number there, so content may reach the bottom margin)

// ---------------------------------------------------------------------------------------------
// Typography (points)
// ---------------------------------------------------------------------------------------------
const TITLE_PT = 34; // content-slide title
const DARK_TITLE_PT = 44; // dark-slide title
const DARK_SUBTITLE_PT = 22; // title-slide subtitle
const FOOTER_PT = 14; // title-slide footer
const NUMBER_PT = 12; // slide number
const HEAD_PT = 20; // column and card heads that are the main label
const CARD_HEAD_PT = 18; // card heads
const BODY_PT = 16; // comfortable body text
const BODY_MIN_PT = 14; // smallest body text allowed
const CAPTION_PT = 12; // captions (never below 11)
const LABEL_PT = 14; // stat labels
const MESSAGE_PT = 22; // key message line
const BOX_MESSAGE_PT = 18; // key message inside a box
const BADGE_NUM_PT = 18; // number inside a numbered circle
const SMALL_BADGE_NUM_PT = 14; // number inside a small numbered circle
const DIAGRAM_LABEL_PT = 12; // labels inside the bootstrap diagram
const MONO_PT = 13; // pose-log example line
const STAT_PT = 54; // large stat value
const STAT_MED_PT = 44; // medium stat value
const STAT_SMALL_PT = 36; // small stat value
const STAT_PRICE_PT = 32; // stat value that is a price range
const BODY_LINE_FACTOR = 1.2; // line height as a multiple of the font size
const BULLET_INDENT_PT = 14; // hanging indent of bullets
const PARA_SPACE_PT = 6; // space after each bullet paragraph (default)
const PARA_SPACE_LOOSE_PT = 12; // space after each bullet paragraph in roomy cards
const NBSP = "\u00a0"; // non-breaking space: keeps a number and its unit on one line
// Units that must stay attached to the number before them (matched after a digit and a space).
const UNIT_PATTERN = /(\d) (mm|min|s|h|percent|degrees|degree C|inch)\b/g;

// Rough text-width model used only to size containers (Calibri/Cambria average character width
// as a fraction of the font size). Deliberately a little wide so that boxes are never too small.
const CHAR_W_REGULAR = 0.46;
const CHAR_W_BOLD = 0.5;
const TEXT_SLACK = 0.06; // extra height added to every estimated text block (inches)

// ---------------------------------------------------------------------------------------------
// Shared component sizes
// ---------------------------------------------------------------------------------------------
const CARD_PAD = 0.25; // inner padding of a card
const CARD_RADIUS = 0.12; // corner radius of cards (inches)
const OUTLINE_PT = 1; // outline weight of white cards
const BADGE_D = 0.55; // numbered circle diameter
const BADGE_SMALL_D = 0.45; // small circle diameter (list rows)
const ICON_BADGE_D = 0.7; // large icon circle diameter
const ICON_GLYPH_RATIO = 0.5; // glyph size as a fraction of its circle
const ICON_RASTER_PX = 256; // icon raster size (>= 256)
const ARROW_GAP = 0.6; // gap between cards that hold an arrow
const ARROW_W = 0.25; // chevron width
const ARROW_H = 0.4; // chevron height
const FLOW_LINE_PT = 2; // weight of connector lines
const FLOW_ROW_GAP = 0.5; // gap between the two rows of the flow slide
const ARROWHEAD_W = 0.3; // down-pointing arrowhead width
const ARROWHEAD_H = 0.2; // down-pointing arrowhead height
const TABLE_BORDER_PT = 0.5; // table rule weight

// ---------------------------------------------------------------------------------------------
// Per-slide settings
// ---------------------------------------------------------------------------------------------
// Title slide graphic (sphere B, sphere A and board, bottom-aligned): sizes in inches
const TITLE_ART = {
	sphereBD: 3.4, // large sphere diameter
	sphereAD: 1.7, // small sphere diameter
	boardW: 2.6, // board width
	boardH: 1.9, // board height
	gapBelowSubtitle: GAP, // gap between subtitle and the top of the graphic
	bottomGap: GAP, // gap between graphic baseline and footer
	outlinePt: 2, // outline weight of the shapes
	boardRadius: 0.1, // board corner radius
	crossLen: 0.5, // length of the TCP cross inside the large sphere
	crossThick: 0.05, // thickness of the TCP cross
};

const PRODUCT = {
	cardH: 2.8, // stat card height
	badgeD: BADGE_D, // icon badge on each card
	valueH: 0.9, // height of the stat value line
	labelH: 0.6, // height of the stat label (two lines)
	messageH: 0.7, // key-message row height
	messageBadgeD: 0.6, // icon badge next to the message
	bodyPt: 20, // body text size
};

const FLOW = {
	numberD: BADGE_D,
	headPt: 18,
	textPt: BODY_MIN_PT,
	headH: 0.35,
};

const FIXTURES = {
	imageCardW: 7.0, // white card holding the figure and its caption
	captionH: 0.5, // caption box height (two lines at CAPTION_PT)
	iconD: ICON_BADGE_D,
	headPt: CARD_HEAD_PT,
	textPt: BODY_MIN_PT,
};

const COST = {
	tableW: 7.4, // table width
	colW: [5.0, 2.4], // table column widths
	cellPt: BODY_MIN_PT,
	cellMargin: [0.04, 0.12, 0.04, 0.12], // cell margins: top, right, bottom, left (inches)
	captionH: 0.3, // caption height (one line)
	statValuePt: STAT_PRICE_PT,
	statValueH: 0.6, // stat value line height
	statLabelH: 0.6, // stat label height (two lines)
};

const SPHERES = {
	iconD: ICON_BADGE_D,
	headPt: HEAD_PT,
	headH: 0.4,
	bulletPt: BODY_PT,
};

const MOUNTING = {
	imageH: 3.5, // height of the larger image
	image2H: 2.7, // height of the smaller image
	cardW: 8.3, // width of the white image card
	captionH: 0.5, // caption height
	pointsPt: BODY_PT,
};

const TCP = {
	imageCardW: 4.3, // white card with the portrait figure
	stepPt: BODY_PT,
	rowCardPad: 0.12, // padding inside a step card (tight so five cards fit)
	get minRowH() {
		return BADGE_D + 2 * this.rowCardPad; // minimum step-card height
	},
};

const BOARD = {
	imageCardW: 5.0, // white card with the figure
	pointPt: BODY_PT,
	rowGap: GAP, // gap between rows
};

const BOOTSTRAP = {
	frameH: 2.0, // height of each mini image frame
	sensorW: 1.4, // sensor rectangle width
	bigD: 0.95, // circle diameter when the sphere is near
	farD: 0.7, // circle diameter when the sphere is farther (drawn smaller)
	offsetX: 0.6, // horizontal shift of the "left" circle from the frame center
	offsetY: 0.35, // vertical shift of the "up" circle from the frame center
	textPt: BODY_MIN_PT,
	textH: 0.6, // two lines of text under each frame
	crossPt: 1, // weight of the crosshair lines in each frame
	pointsPt: 18,
	sensorPt: 16, // "Sensor" label size
	lensD: 0.45, // lens circle on the sensor
	frameLineGap: 0.25, // margin of the crosshair from the frame edge
};

const PLAN = {
	imageCardW: 7.9, // white card with the plan picture and caption
	captionH: 0.5,
	valuePt: STAT_MED_PT,
	valueW: 1.3, // width reserved for the stat value
	labelPt: LABEL_PT,
};

const LOOP = {
	cardH: 2.7, // step cards
	headPt: 18,
	textPt: BODY_MIN_PT,
	headH: 0.35,
	statValuePt: STAT_SMALL_PT,
	statValueH: 0.6, // stat value line height
	statLabelH: 0.6, // stat label height
	rowH: 1.8, // lower row (stats and message)
	messageBadgeD: ICON_BADGE_D,
};

const MANIFEST = {
	headBarH: 0.7, // filled header block inside each card
	headPt: CARD_HEAD_PT,
	bulletPt: 18,
	exampleBoxH: 0.8,
	exampleBadgeD: BADGE_SMALL_D + 0.1,
};

const CHECKS = {
	iconD: ICON_BADGE_D,
	headPt: HEAD_PT,
	flagPt: 18,
	textPt: BODY_PT,
	captionH: 0.3,
};

const INDEPENDENT = {
	iconD: ICON_BADGE_D,
	headPt: HEAD_PT,
	bulletPt: 18,
	messageH: 1.3, // message box height
	messageIconD: ICON_BADGE_D,
};

const SPOILERS = {
	columns: 2,
	rowsFirstColumn: 4, // 4 + 3 items
	textPt: BODY_PT,
	iconD: BADGE_D + 0.1,
	cardPad: GAP_TIGHT, // padding inside each item card (smaller than CARD_PAD so four rows fit)
};

const DELIVERABLES = {
	listW: 7.5, // checklist column width
	textPt: BODY_PT,
	iconD: BADGE_SMALL_D,
	headPt: HEAD_PT,
	softwareIconD: ICON_BADGE_D,
	bulletPt: BODY_PT,
};

const NEXT = {
	groupShares: [3.0, 3.0, 3.8], // relative widths of Open, Decided, Next steps
	headPt: HEAD_PT,
	headH: 0.45,
	itemPt: BODY_PT,
	iconD: BADGE_SMALL_D,
};

// Labels that are not content from the JSON but are needed to read a diagram or group.
const EXTRA_LABELS = {
	sensor: "Sensor", // bootstrap diagram
	openHead: "Open",
	decidedHead: "Decided",
	stepsHead: "Next steps",
};

// ---------------------------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------------------------

/** Number of lines a text needs when wrapped greedily at the given width (inches) and size (pt). */
function countLines(text, widthIn, pt, bold = false) {
	const charW = (pt * (bold ? CHAR_W_BOLD : CHAR_W_REGULAR)) / 72;
	const maxChars = Math.max(1, Math.floor(widthIn / charW));
	let lines = 1;
	let used = 0;
	for (const word of String(text).split(" ")) {
		const need = used === 0 ? word.length : used + 1 + word.length;
		if (need <= maxChars) {
			used = need;
		} else {
			lines += used === 0 ? 0 : 1;
			used = word.length;
		}
	}
	return lines;
}

/** Estimated height (inches) of a wrapped text block. */
function textHeight(text, widthIn, pt, bold = false) {
	return (countLines(text, widthIn, pt, bold) * pt * BODY_LINE_FACTOR) / 72 + TEXT_SLACK;
}

/** Estimated height of a bulleted list (each item one paragraph). */
function bulletsHeight(items, widthIn, pt) {
	const indentIn = BULLET_INDENT_PT / 72;
	let total = 0;
	for (const item of items) total += textHeight(item, widthIn - indentIn, pt) - TEXT_SLACK + PARA_SPACE_PT / 72;
	return total + TEXT_SLACK;
}

/** Keep numbers and their units together (non-breaking space). */
function glue(str) {
	return String(str).replace(UNIT_PATTERN, "$1" + NBSP + "$2");
}

/** Render a react-icons component to a white (or colored) PNG data URI. */
async function renderIcon(Component, hex) {
	const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Component, { color: "#" + hex, size: String(ICON_RASTER_PX) }));
	const png = await sharp(Buffer.from(svg)).resize(ICON_RASTER_PX, ICON_RASTER_PX, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } }).png().toBuffer();
	return "image/png;base64," + png.toString("base64");
}

// ---------------------------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------------------------
async function main() {
	const content = JSON.parse(fs.readFileSync(CONTENT_JSON, "utf8"));

	const pres = new pptxgen();
	pres.layout = "LAYOUT_WIDE";
	pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
	pres.title = "Stage-1 Calibration Captures";
	pres.author = "Depth calibration from spherical target";
	pres.subject = "Stage-1 capture procedure overview";
	const C = pres.SchemeColor; // scheme colors: text1 dk1, text2 dk2, background1 lt1, background2 lt2, accent1..6

	// ---- Icons (white glyphs on colored circles; one teal glyph for list check marks) ----------
	const WHITE_HEX = THEME.colors.lt1;
	const TEAL_HEX = THEME.colors.accent2;
	const iconSources = {
		spray: fa.FaSprayCan,
		ruler: fa.FaRulerHorizontal,
		wrench: fa.FaWrench,
		circle: fa.FaCircle,
		square: fa.FaSquareFull,
		check: fa.FaCheck,
		warning: fa.FaExclamationTriangle,
		move: fa.FaArrowsAlt,
		sliders: fa.FaSlidersH,
		edit: fa.FaEdit,
		tool: fa.FaTools,
		hand: fa.FaHandPaper,
		eye: fa.FaEye,
		swap: fa.FaExchangeAlt,
		clipboard: fa.FaClipboardList,
		clock: fa.FaClock,
		bullseye: fa.FaBullseye,
		list: fa.FaListOl,
		fileCode: fa.FaFileCode,
		fileList: fa.FaListAlt,
		fileAlt: fa.FaFileAlt,
		code: fa.FaCode,
		question: fa.FaQuestion,
		table: fa.FaTable,
		board: fa.FaBorderAll,
		camera: fa.FaCamera,
	};
	const iconWhite = {};
	for (const [key, comp] of Object.entries(iconSources)) iconWhite[key] = await renderIcon(comp, WHITE_HEX);
	const iconTealCheckSquare = await renderIcon(fa.FaCheckSquare, TEAL_HEX);

	// ---- Images: read pixel sizes so aspect ratios are exact ---------------------------------
	const imageInfo = {};
	async function loadImage(relPath) {
		if (!imageInfo[relPath]) {
			const full = path.join(PRESENTATIONS_DIR, relPath);
			const meta = await sharp(full).metadata();
			imageInfo[relPath] = { full, w: meta.width, h: meta.height };
		}
		return imageInfo[relPath];
	}
	for (const s of content.slides) {
		if (s.image) await loadImage(s.image);
		if (s.image2) await loadImage(s.image2);
	}

	// ---- Layouts -----------------------------------------------------------------------------
	pres.defineSlideMaster({
		title: "TITLE_DARK",
		background: { color: C.text2 },
		objects: [
			{ placeholder: { options: { name: "title", type: "title", x: MARGIN, y: MARGIN, w: CONTENT_W, h: DARK_TITLE_H, fontFace: HEAD_FONT_REF, fontSize: DARK_TITLE_PT, bold: true, color: C.background1, align: "left", valign: "top", margin: 0 }, text: "Title" } },
			{ placeholder: { options: { name: "subtitle", type: "body", x: MARGIN, y: DARK_SUBTITLE_Y, w: DARK_SUBTITLE_W, h: DARK_SUBTITLE_H, fontSize: DARK_SUBTITLE_PT, color: C.accent6, align: "left", valign: "top", margin: 0 }, text: "Subtitle" } },
			{ placeholder: { options: { name: "footer", type: "body", x: MARGIN, y: DARK_FOOTER_Y, w: CONTENT_W, h: DARK_FOOTER_H, fontSize: FOOTER_PT, color: C.accent6, align: "left", valign: "bottom", margin: 0 }, text: "Footer" } },
		],
	});
	pres.defineSlideMaster({
		title: "TITLE_ONLY",
		background: { color: C.background1 },
		objects: [{ placeholder: { options: { name: "title", type: "title", x: CONTENT_X, y: TITLE_Y, w: CONTENT_W, h: TITLE_H, fontFace: HEAD_FONT_REF, fontSize: TITLE_PT, bold: true, color: C.text2, align: "left", valign: "top", margin: 0 }, text: "Title" } }],
		slideNumber: { x: SLIDE_W - MARGIN - NUMBER_W, y: NUMBER_Y, w: NUMBER_W, h: NUMBER_H, fontSize: NUMBER_PT, color: C.accent5, align: "right", valign: "bottom", margin: 0 },
	});

	// ---- Drawing helpers (bound to this presentation) ----------------------------------------
	const R = pres.ShapeType;

	/** Text box: no padding, top-aligned by default, always a real text box. */
	function text(slide, name, runs, x, y, w, h, o = {}) {
		runs = typeof runs === "string" ? glue(runs) : runs.map((r) => Object.assign({}, r, { text: glue(r.text) }));
		slide.addText(runs, Object.assign({ x, y, w, h, margin: 0, valign: "top", align: "left", color: C.text1, fontSize: BODY_PT, isTextBox: true, objectName: name }, o));
	}

	/** Bulleted list from an array of strings. */
	function bullets(slide, name, items, x, y, w, h, o = {}) {
		const space = o.paraSpacePt === undefined ? PARA_SPACE_PT : o.paraSpacePt;
		const runs = items.map((t, i) => ({ text: t, options: { bullet: { indent: BULLET_INDENT_PT }, breakLine: i < items.length - 1, paraSpaceAfter: space } }));
		const rest = Object.assign({}, o);
		delete rest.paraSpacePt;
		text(slide, name, runs, x, y, w, h, rest);
	}

	/** Card: "tint" (lt2 fill) or "white" (white with a pale outline, used behind figures). */
	function card(slide, name, x, y, w, h, kind = "tint") {
		const opts = { x, y, w, h, rectRadius: CARD_RADIUS, objectName: name };
		if (kind === "tint") {
			opts.fill = { color: C.background2 };
			opts.line = { type: "none" };
		} else if (kind === "dark") {
			opts.fill = { color: C.text1 };
			opts.line = { type: "none" };
		} else {
			opts.fill = { color: C.background1 };
			opts.line = { color: C.accent6, width: OUTLINE_PT };
		}
		slide.addShape(R.roundRect, opts);
	}

	/** Solid circle with a centered number. */
	function numberBadge(slide, name, n, x, y, d, fill, pt = BADGE_NUM_PT) {
		slide.addText(String(n), { x, y, w: d, h: d, shape: R.ellipse, fill: { color: fill }, line: { type: "none" }, color: C.background1, bold: true, fontSize: pt, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: name });
	}

	/** Solid circle with a centered white icon glyph. */
	function iconBadge(slide, name, iconKey, x, y, d, fill) {
		slide.addShape(R.ellipse, { x, y, w: d, h: d, fill: { color: fill }, line: { type: "none" }, objectName: name + " circle" });
		const g = d * ICON_GLYPH_RATIO;
		slide.addImage({ data: iconWhite[iconKey], x: x + (d - g) / 2, y: y + (d - g) / 2, w: g, h: g, altText: iconKey + " icon", objectName: name + " glyph" });
	}

	/** Place an image inside a box with "contain" semantics (exact aspect ratio). */
	function fitImage(slide, name, rel, bx, by, bw, bh, align = "center") {
		const info = imageInfo[rel];
		const ar = info.w / info.h;
		let w = bw;
		let h = w / ar;
		if (h > bh) {
			h = bh;
			w = h * ar;
		}
		const x = align === "left" ? bx : bx + (bw - w) / 2;
		const y = bottomAligned(align) ? by + bh - h : by + (bh - h) / 2;
		slide.addImage({ path: info.full, x, y, w, h, altText: name, objectName: name });
		return { x, y, w, h };
	}
	function bottomAligned(a) {
		return a === "bottom-left";
	}

	/** Stat callout: value above label (stacked) inside a tint card. */
	function statCard(slide, name, stat, x, y, w, h, valuePt, valueH, labelH, labelPt = LABEL_PT) {
		card(slide, name + " card", x, y, w, h);
		// Value and label form one block, centered vertically in the card
		const top = y + (h - valueH - labelH) / 2;
		text(slide, name + " value", stat.value, x + CARD_PAD, top, w - 2 * CARD_PAD, valueH, { fontFace: HEAD_FONT_REF, fontSize: valuePt, bold: true, color: C.accent1, valign: "middle" });
		text(slide, name + " label", stat.label, x + CARD_PAD, top + valueH, w - 2 * CARD_PAD, labelH, { fontSize: labelPt });
	}

	/** Title (placeholder) of a content or dark slide. */
	function title(slide, str) {
		slide.addText(str, { placeholder: "title" });
	}

	/**
	 * A vertical list of rows, each with a badge on the left and wrapped text on the right.
	 * Returns the y just below the last row.
	 * opts: x, y, w, pt, badge(i,item)->{kind:'num'|'icon'|'glyph', ...}, badgeD, cardKind (null|'tint'|'dark'|'white'),
	 *       textColor, gap, minRowH
	 */
	function rowList(slide, name, items, o) {
		let y = o.y;
		const pad = o.cardKind ? o.cardPad : 0;
		const textX = o.x + pad + o.badgeD + GAP_TIGHT;
		const textW = o.w - pad * 2 - o.badgeD - GAP_TIGHT;
		items.forEach((item, i) => {
			const str = typeof item === "string" ? item : item.text;
			const textH = textHeight(str, textW, o.pt);
			const inner = Math.max(o.badgeD, textH);
			const rowH = Math.max(o.minRowH || 0, inner + pad * 2);
			if (o.cardKind) card(slide, `${name} row ${i + 1} card`, o.x, y, o.w, rowH, o.cardKind);
			const by = y + (rowH - o.badgeD) / 2;
			const b = o.badge(i, item);
			if (b.kind === "num") numberBadge(slide, `${name} badge ${i + 1}`, b.n, o.x + pad, by, o.badgeD, b.fill, o.badgePt || BADGE_NUM_PT);
			else if (b.kind === "icon") iconBadge(slide, `${name} icon ${i + 1}`, b.icon, o.x + pad, by, o.badgeD, b.fill);
			else slide.addImage({ data: b.data, x: o.x + pad, y: by, w: o.badgeD, h: o.badgeD, altText: "check icon", objectName: `${name} check ${i + 1}` });
			text(slide, `${name} text ${i + 1}`, str, textX, y, textW, rowH, { fontSize: o.pt, color: o.textColor || C.text1, valign: "middle" });
			y += rowH + (o.gap === undefined ? GAP_TIGHT : o.gap);
		});
		return y - (o.gap === undefined ? GAP_TIGHT : o.gap);
	}

	// ---- Slide builders ----------------------------------------------------------------------
	const builders = {};

	builders.title = (slide, s) => {
		title(slide, s.title);
		slide.addText(s.subtitle, { placeholder: "subtitle" });
		slide.addText(s.footer, { placeholder: "footer" });
		// Graphic: sphere B, sphere A and the board, sitting on one baseline (native shapes).
		const a = TITLE_ART;
		const baseline = DARK_FOOTER_Y - a.bottomGap;
		const sphereBX = MARGIN;
		slide.addShape(R.ellipse, { x: sphereBX, y: baseline - a.sphereBD, w: a.sphereBD, h: a.sphereBD, fill: { color: C.accent2 }, line: { color: C.accent6, width: a.outlinePt }, objectName: "Graphic sphere B" });
		// TCP cross at the center of sphere B
		const bcx = sphereBX + a.sphereBD / 2;
		const bcy = baseline - a.sphereBD / 2;
		slide.addShape(R.rect, { x: bcx - a.crossLen / 2, y: bcy - a.crossThick / 2, w: a.crossLen, h: a.crossThick, fill: { color: C.background1 }, line: { type: "none" }, objectName: "Graphic sphere B cross horizontal" });
		slide.addShape(R.rect, { x: bcx - a.crossThick / 2, y: bcy - a.crossLen / 2, w: a.crossThick, h: a.crossLen, fill: { color: C.background1 }, line: { type: "none" }, objectName: "Graphic sphere B cross vertical" });
		const sphereAX = sphereBX + a.sphereBD + GAP;
		slide.addShape(R.ellipse, { x: sphereAX, y: baseline - a.sphereAD, w: a.sphereAD, h: a.sphereAD, fill: { color: C.accent1 }, line: { color: C.accent6, width: a.outlinePt }, objectName: "Graphic sphere A" });
		const boardX = sphereAX + a.sphereAD + GAP;
		slide.addShape(R.roundRect, { x: boardX, y: baseline - a.boardH, w: a.boardW, h: a.boardH, rectRadius: a.boardRadius, fill: { color: C.accent6 }, line: { color: C.accent3, width: a.outlinePt }, objectName: "Graphic board" });
	};

	builders.product = (slide, s) => {
		title(slide, s.title);
		const p = PRODUCT;
		const cardW = (CONTENT_W - 2 * GAP) / s.stats.length;
		const statIcons = ["clipboard", "clock", "bullseye"];
		s.stats.forEach((st, i) => {
			const x = CONTENT_X + i * (cardW + GAP);
			card(slide, `Stat ${i + 1} card`, x, CONTENT_TOP, cardW, p.cardH);
			iconBadge(slide, `Stat ${i + 1} icon`, statIcons[i], x + CARD_PAD, CONTENT_TOP + CARD_PAD, p.badgeD, C.accent2);
			const vy = CONTENT_TOP + CARD_PAD + p.badgeD + GAP_TIGHT / 2;
			text(slide, `Stat ${i + 1} value`, st.value, x + CARD_PAD, vy, cardW - 2 * CARD_PAD, p.valueH, { fontFace: HEAD_FONT_REF, fontSize: STAT_PT, bold: true, color: C.accent1, valign: "middle" });
			text(slide, `Stat ${i + 1} label`, st.label, x + CARD_PAD, vy + p.valueH, cardW - 2 * CARD_PAD, p.labelH, { fontSize: LABEL_PT });
		});
		const my = CONTENT_TOP + p.cardH + GAP;
		iconBadge(slide, "Message icon", "table", CONTENT_X, my + (p.messageH - p.messageBadgeD) / 2, p.messageBadgeD, C.accent1);
		text(slide, "Key message", s.message, CONTENT_X + p.messageBadgeD + GAP_TIGHT, my, CONTENT_W - p.messageBadgeD - GAP_TIGHT, p.messageH, { fontSize: MESSAGE_PT, bold: true, italic: true, color: C.text2, valign: "middle" });
		const by = my + p.messageH + GAP;
		text(slide, "Body", s.body, CONTENT_X, by, CONTENT_W, CONTENT_BOTTOM - by, { fontSize: p.bodyPt });
	};

	builders.flow = (slide, s) => {
		title(slide, s.title);
		const f = FLOW;
		const perRow = s.steps.length / 2;
		const cardW = (CONTENT_W - (perRow - 1) * ARROW_GAP) / perRow;
		const cardH = (CONTENT_H - FLOW_ROW_GAP) / 2;
		const pos = (i) => ({ x: CONTENT_X + (i % perRow) * (cardW + ARROW_GAP), y: CONTENT_TOP + Math.floor(i / perRow) * (cardH + FLOW_ROW_GAP) });
		s.steps.forEach((st, i) => {
			const { x, y } = pos(i);
			card(slide, `Step ${st.n} card`, x, y, cardW, cardH);
			numberBadge(slide, `Step ${st.n} badge`, st.n, x + CARD_PAD, y + CARD_PAD, f.numberD, C.accent1);
			const hy = y + CARD_PAD + f.numberD + GAP_TIGHT / 2;
			text(slide, `Step ${st.n} head`, st.head, x + CARD_PAD, hy, cardW - 2 * CARD_PAD, f.headH, { fontSize: f.headPt, bold: true, color: C.text2 });
			const ty = hy + f.headH;
			text(slide, `Step ${st.n} text`, st.text, x + CARD_PAD, ty, cardW - 2 * CARD_PAD, y + cardH - CARD_PAD - ty, { fontSize: f.textPt });
			// Chevron to the next card in the same row
			if (i % perRow !== perRow - 1) {
				slide.addShape(R.chevron, { x: x + cardW + (ARROW_GAP - ARROW_W) / 2, y: y + (cardH - ARROW_H) / 2, w: ARROW_W, h: ARROW_H, fill: { color: C.accent2 }, line: { type: "none" }, objectName: `Arrow ${st.n} to ${st.n + 1}` });
			}
		});
		// Return connector from the end of row 1 down and back to the start of row 2
		const last1 = pos(perRow - 1);
		const first2 = pos(perRow);
		const startX = last1.x + cardW / 2;
		const endX = first2.x + cardW / 2;
		const startY = last1.y + cardH;
		const midY = startY + FLOW_ROW_GAP / 2;
		const endY = first2.y - ARROWHEAD_H;
		const line = () => ({ line: { color: C.accent2, width: FLOW_LINE_PT } });
		slide.addShape(R.line, Object.assign({ x: startX, y: startY, w: 0, h: midY - startY, objectName: "Return connector down" }, line()));
		slide.addShape(R.line, Object.assign({ x: endX, y: midY, w: startX - endX, h: 0, objectName: "Return connector across" }, line()));
		slide.addShape(R.line, Object.assign({ x: endX, y: midY, w: 0, h: endY - midY, objectName: "Return connector into row 2" }, line()));
		slide.addShape(R.triangle, { x: endX - ARROWHEAD_W / 2, y: endY, w: ARROWHEAD_W, h: ARROWHEAD_H, flipV: true, fill: { color: C.accent2 }, line: { type: "none" }, objectName: "Return connector arrowhead" });
	};

	builders.fixtures = (slide, s) => {
		title(slide, s.title);
		const f = FIXTURES;
		const cardW = f.imageCardW;
		const info = imageInfo[s.image];
		const innerW = cardW - 2 * CARD_PAD;
		card(slide, "Figure card", CONTENT_X, CONTENT_TOP, cardW, CONTENT_H, "white");
		// Figure and caption are centered vertically as a group inside the card
		const imgH = innerW * (info.h / info.w);
		const groupH = imgH + GAP_TIGHT + f.captionH;
		const gy = CONTENT_TOP + (CONTENT_H - groupH) / 2;
		fitImage(slide, "Sphere on stem, side view", s.image, CONTENT_X + CARD_PAD, gy, innerW, imgH);
		text(slide, "Figure caption", s.caption, CONTENT_X + CARD_PAD, gy + imgH + GAP_TIGHT, innerW, f.captionH, { fontSize: CAPTION_PT, color: C.accent5 });
		const rx = CONTENT_X + cardW + GAP;
		const rw = CONTENT_W - cardW - GAP;
		const cardH = (CONTENT_H - 2 * GAP) / s.cards.length;
		const icons = ["circle", "circle", "board"];
		s.cards.forEach((c, i) => {
			const y = CONTENT_TOP + i * (cardH + GAP);
			card(slide, `Fixture ${i + 1} card`, rx, y, rw, cardH);
			iconBadge(slide, `Fixture ${i + 1} icon`, icons[i], rx + CARD_PAD, y + (cardH - f.iconD) / 2, f.iconD, C.accent2);
			const tx = rx + CARD_PAD + f.iconD + GAP_TIGHT;
			const tw = rw - 2 * CARD_PAD - f.iconD - GAP_TIGHT;
			text(slide, `Fixture ${i + 1} text`, [{ text: c.head, options: { fontSize: f.headPt, bold: true, color: C.text2, breakLine: true } }, { text: c.text, options: { fontSize: f.textPt } }], tx, y + CARD_PAD, tw, cardH - 2 * CARD_PAD, { valign: "middle" });
		});
	};

	builders.cost = (slide, s) => {
		title(slide, s.title);
		const c = COST;
		const headCell = (t, align) => ({ text: glue(t), options: { bold: true, color: C.background1, fill: { color: C.text2 }, align, valign: "middle", fontSize: c.cellPt, margin: c.cellMargin } });
		const rows = [[headCell(s.table.header[0], "left"), headCell(s.table.header[1], "right")]];
		s.table.rows.forEach((r, i) => {
			const fill = { color: i % 2 === 0 ? C.background1 : C.background2 };
			const base = { fill, color: C.text1, valign: "middle", fontSize: c.cellPt, margin: c.cellMargin };
			rows.push([{ text: glue(r[0]), options: Object.assign({ align: "left" }, base) }, { text: glue(r[1]), options: Object.assign({ align: "right", bold: true }, base) }]);
		});
		const captionY = CONTENT_BOTTOM - c.captionH;
		const statsH = captionY - GAP - CONTENT_TOP; // the table and the stat column share this height
		slide.addTable(rows, { x: CONTENT_X, y: CONTENT_TOP, w: c.tableW, colW: c.colW, rowH: statsH / rows.length, border: { type: "solid", pt: TABLE_BORDER_PT, color: C.accent6 }, objectName: "Cost table" });
		const rx = CONTENT_X + c.tableW + GAP;
		const rw = CONTENT_W - c.tableW - GAP;
		const cardH = (statsH - GAP) / s.stats.length;
		s.stats.forEach((st, i) => {
			statCard(slide, `Total ${i + 1}`, st, rx, CONTENT_TOP + i * (cardH + GAP), rw, cardH, c.statValuePt, c.statValueH, c.statLabelH);
		});
		text(slide, "Cost caption", s.caption, CONTENT_X, captionY, CONTENT_W, c.captionH, { fontSize: CAPTION_PT, color: C.accent5, valign: "bottom" });
	};

	builders.spheres = (slide, s) => {
		title(slide, s.title);
		const sp = SPHERES;
		const cardW = (CONTENT_W - 2 * GAP) / s.columns.length;
		s.columns.forEach((col, i) => {
			const x = CONTENT_X + i * (cardW + GAP);
			card(slide, `Column ${i + 1} card`, x, CONTENT_TOP, cardW, CONTENT_H);
			iconBadge(slide, `Column ${i + 1} icon`, col.icon, x + CARD_PAD, CONTENT_TOP + CARD_PAD, sp.iconD, C.accent2);
			const hy = CONTENT_TOP + CARD_PAD + sp.iconD + GAP_TIGHT;
			text(slide, `Column ${i + 1} head`, col.head, x + CARD_PAD, hy, cardW - 2 * CARD_PAD, sp.headH, { fontFace: HEAD_FONT_REF, fontSize: sp.headPt, bold: true, color: C.text2 });
			const by = hy + sp.headH + GAP_TIGHT / 2;
			bullets(slide, `Column ${i + 1} points`, col.points, x + CARD_PAD, by, cardW - 2 * CARD_PAD, CONTENT_TOP + CONTENT_H - CARD_PAD - by, { fontSize: sp.bulletPt, paraSpacePt: PARA_SPACE_LOOSE_PT });
		});
	};

	builders.mounting = (slide, s) => {
		title(slide, s.title);
		const m = MOUNTING;
		const cardW = m.cardW;
		const innerW = cardW - 2 * CARD_PAD;
		card(slide, "Figures card", CONTENT_X, CONTENT_TOP, cardW, CONTENT_H, "white");
		// Two images on a common baseline: image larger, image2 smaller
		const i1 = imageInfo[s.image];
		const i2 = imageInfo[s.image2];
		const w1 = m.imageH * (i1.w / i1.h);
		const w2 = m.image2H * (i2.w / i2.h);
		const rowW = w1 + GAP + w2;
		const groupH = m.imageH + GAP_TIGHT + m.captionH;
		const gy = CONTENT_TOP + (CONTENT_H - groupH) / 2;
		const rx0 = CONTENT_X + CARD_PAD + (innerW - rowW) / 2;
		const baseline = gy + m.imageH;
		fitImage(slide, "Adapter on flange with stem", s.image, rx0, gy, w1, m.imageH, "bottom-left");
		fitImage(slide, "Steel sphere with bonded stem", s.image2, rx0 + w1 + GAP, baseline - m.image2H, w2, m.image2H, "bottom-left");
		text(slide, "Figures caption", s.caption, CONTENT_X + CARD_PAD, baseline + GAP_TIGHT, innerW, m.captionH, { fontSize: CAPTION_PT, color: C.accent5 });
		const px = CONTENT_X + cardW + GAP;
		const pw = CONTENT_W - cardW - GAP;
		card(slide, "Points card", px, CONTENT_TOP, pw, CONTENT_H);
		bullets(slide, "Mounting points", s.points, px + CARD_PAD, CONTENT_TOP + CARD_PAD, pw - 2 * CARD_PAD, CONTENT_H - 2 * CARD_PAD, { fontSize: m.pointsPt, valign: "middle" });
	};

	builders.tcp = (slide, s) => {
		title(slide, s.title);
		const t = TCP;
		card(slide, "Figure card", CONTENT_X, CONTENT_TOP, t.imageCardW, CONTENT_H, "white");
		fitImage(slide, "Finding the tool center point with a three-ball nest", s.image, CONTENT_X + CARD_PAD, CONTENT_TOP + CARD_PAD, t.imageCardW - 2 * CARD_PAD, CONTENT_H - 2 * CARD_PAD);
		const rx = CONTENT_X + t.imageCardW + GAP;
		const rw = CONTENT_W - t.imageCardW - GAP;
		// Step cards share the available height equally (rows grow only if text needs it)
		const texts = s.steps.map((st) => st.text);
		const need = texts.map((tx) => Math.max(t.minRowH, textHeight(tx, rw - 2 * t.rowCardPad - BADGE_D - GAP_TIGHT, t.stepPt) + 2 * t.rowCardPad));
		const extra = (CONTENT_H - (s.steps.length - 1) * GAP_TIGHT - need.reduce((a, b) => a + b, 0)) / s.steps.length;
		let y = CONTENT_TOP;
		s.steps.forEach((st, i) => {
			const rowH = need[i] + Math.max(0, extra);
			card(slide, `Step ${st.n} card`, rx, y, rw, rowH);
			numberBadge(slide, `Step ${st.n} badge`, st.n, rx + t.rowCardPad, y + (rowH - BADGE_D) / 2, BADGE_D, C.accent1);
			const tx = rx + t.rowCardPad + BADGE_D + GAP_TIGHT;
			text(slide, `Step ${st.n} text`, st.text, tx, y, rx + rw - t.rowCardPad - tx, rowH, { fontSize: t.stepPt, valign: "middle" });
			y += rowH + GAP_TIGHT;
		});
	};

	builders.board = (slide, s) => {
		title(slide, s.title);
		const b = BOARD;
		card(slide, "Figure card", CONTENT_X, CONTENT_TOP, b.imageCardW, CONTENT_H, "white");
		fitImage(slide, "Board on the flange with its tool frame", s.image, CONTENT_X + CARD_PAD, CONTENT_TOP + CARD_PAD, b.imageCardW - 2 * CARD_PAD, CONTENT_H - 2 * CARD_PAD);
		const rx = CONTENT_X + b.imageCardW + GAP;
		const rw = CONTENT_W - b.imageCardW - GAP;
		// Rows are spread over the full height so the list is centered against the figure
		const rowH = (CONTENT_H - (s.points.length - 1) * b.rowGap) / s.points.length;
		rowList(slide, "Board point", s.points, { x: rx, y: CONTENT_TOP, w: rw, pt: b.pointPt, badgeD: BADGE_SMALL_D, gap: b.rowGap, minRowH: rowH, cardKind: null, cardPad: 0, badge: () => ({ kind: "icon", icon: "check", fill: C.accent2 }) });
	};

	builders.bootstrap = (slide, s) => {
		title(slide, s.title);
		const b = BOOTSTRAP;
		// Sensor rectangle on the left, drawn the same height as the frames
		const sensorX = CONTENT_X;
		const sensorY = CONTENT_TOP;
		slide.addShape(R.roundRect, { x: sensorX, y: sensorY, w: b.sensorW, h: b.frameH, rectRadius: CARD_RADIUS, fill: { color: C.text2 }, line: { type: "none" }, objectName: "Sensor body" });
		slide.addShape(R.ellipse, { x: sensorX + (b.sensorW - b.lensD) / 2, y: sensorY + CARD_PAD, w: b.lensD, h: b.lensD, fill: { color: C.accent3 }, line: { type: "none" }, objectName: "Sensor lens" });
		text(slide, "Sensor label", EXTRA_LABELS.sensor, sensorX, sensorY + CARD_PAD + b.lensD + GAP_TIGHT / 2, b.sensorW, b.frameH - (CARD_PAD + b.lensD + GAP_TIGHT / 2), { fontSize: b.sensorPt, bold: true, color: C.background1, align: "center", valign: "top" });
		// Frames, one per bootstrap capture: what the sensor sees
		const framesX = sensorX + b.sensorW + ARROW_GAP;
		const n = s.boot.length;
		const frameW = (CONTENT_X + CONTENT_W - framesX - (n - 1) * GAP) / n;
		slide.addShape(R.chevron, { x: sensorX + b.sensorW + (ARROW_GAP - ARROW_W) / 2, y: sensorY + (b.frameH - ARROW_H) / 2, w: ARROW_W, h: ARROW_H, fill: { color: C.accent2 }, line: { type: "none" }, objectName: "Sensor view arrow" });
		// Where each circle sits relative to the frame center, and its size
		const placement = [
			{ dx: 0, dy: 0, d: b.bigD }, // boot01: center
			{ dx: -b.offsetX, dy: 0, d: b.bigD }, // boot02: left
			{ dx: 0, dy: -b.offsetY, d: b.bigD }, // boot03: up
			{ dx: 0, dy: 0, d: b.farD }, // boot04: farther, so drawn smaller
		];
		s.boot.forEach((bt, i) => {
			const fx = framesX + i * (frameW + GAP);
			card(slide, `Frame ${bt.id}`, fx, sensorY, frameW, b.frameH, "white");
			const cx = fx + frameW / 2;
			const cy = sensorY + b.frameH / 2;
			const cross = () => ({ line: { color: C.accent6, width: b.crossPt } });
			slide.addShape(R.line, Object.assign({ x: fx + b.frameLineGap, y: cy, w: frameW - 2 * b.frameLineGap, h: 0, objectName: `Frame ${bt.id} crosshair horizontal` }, cross()));
			slide.addShape(R.line, Object.assign({ x: cx, y: sensorY + b.frameLineGap, w: 0, h: b.frameH - 2 * b.frameLineGap, objectName: `Frame ${bt.id} crosshair vertical` }, cross()));
			const p = placement[i];
			slide.addText(bt.id, { x: cx + p.dx - p.d / 2, y: cy + p.dy - p.d / 2, w: p.d, h: p.d, shape: R.ellipse, fill: { color: C.accent1 }, line: { type: "none" }, color: C.background1, bold: true, fontSize: DIAGRAM_LABEL_PT, align: "center", valign: "middle", margin: 0, wrap: false, isTextBox: true, objectName: `Circle ${bt.id}` });
			text(slide, `Text ${bt.id}`, bt.text, fx, sensorY + b.frameH + GAP_TIGHT, frameW, b.textH, { fontSize: b.textPt });
		});
		const py = sensorY + b.frameH + GAP_TIGHT + b.textH + GAP;
		card(slide, "Points card", CONTENT_X, py, CONTENT_W, CONTENT_BOTTOM - py);
		bullets(slide, "Bootstrap points", s.points, CONTENT_X + CARD_PAD, py + CARD_PAD, CONTENT_W - 2 * CARD_PAD, CONTENT_BOTTOM - py - 2 * CARD_PAD, { fontSize: b.pointsPt, valign: "middle" });
	};

	builders.plan = (slide, s) => {
		title(slide, s.title);
		const p = PLAN;
		const info = imageInfo[s.image];
		const innerW = p.imageCardW - 2 * CARD_PAD;
		const imgH = innerW * (info.h / info.w);
		const cardH = CARD_PAD + imgH + GAP_TIGHT + p.captionH + CARD_PAD;
		card(slide, "Figure card", CONTENT_X, CONTENT_TOP, p.imageCardW, cardH, "white");
		fitImage(slide, "Planned poses: side view and front view", s.image, CONTENT_X + CARD_PAD, CONTENT_TOP + CARD_PAD, innerW, imgH);
		text(slide, "Figure caption", s.caption, CONTENT_X + CARD_PAD, CONTENT_TOP + CARD_PAD + imgH + GAP_TIGHT, innerW, p.captionH, { fontSize: CAPTION_PT, color: C.accent5 });
		const rx = CONTENT_X + p.imageCardW + GAP;
		const rw = CONTENT_W - p.imageCardW - GAP;
		const statH = (cardH - (s.stats.length - 1) * GAP) / s.stats.length;
		s.stats.forEach((st, i) => {
			const y = CONTENT_TOP + i * (statH + GAP);
			card(slide, `Stat ${i + 1} card`, rx, y, rw, statH);
			text(slide, `Stat ${i + 1} value`, st.value, rx + CARD_PAD, y, p.valueW, statH, { fontFace: HEAD_FONT_REF, fontSize: p.valuePt, bold: true, color: C.accent1, valign: "middle" });
			const lx = rx + CARD_PAD + p.valueW + GAP_TIGHT;
			text(slide, `Stat ${i + 1} label`, st.label, lx, y, rx + rw - CARD_PAD - lx, statH, { fontSize: p.labelPt, valign: "middle" });
		});
	};

	builders.loop = (slide, s) => {
		title(slide, s.title);
		const l = LOOP;
		const n = s.steps.length;
		const cardW = (CONTENT_W - (n - 1) * ARROW_GAP) / n;
		s.steps.forEach((st, i) => {
			const x = CONTENT_X + i * (cardW + ARROW_GAP);
			card(slide, `Step ${st.n} card`, x, CONTENT_TOP, cardW, l.cardH);
			numberBadge(slide, `Step ${st.n} badge`, st.n, x + CARD_PAD, CONTENT_TOP + CARD_PAD, BADGE_D, C.accent1);
			const hy = CONTENT_TOP + CARD_PAD + BADGE_D + GAP_TIGHT / 2;
			text(slide, `Step ${st.n} head`, st.head, x + CARD_PAD, hy, cardW - 2 * CARD_PAD, l.headH, { fontSize: l.headPt, bold: true, color: C.text2 });
			const ty = hy + l.headH;
			text(slide, `Step ${st.n} text`, st.text, x + CARD_PAD, ty, cardW - 2 * CARD_PAD, CONTENT_TOP + l.cardH - CARD_PAD - ty, { fontSize: l.textPt });
			if (i < n - 1) slide.addShape(R.chevron, { x: x + cardW + (ARROW_GAP - ARROW_W) / 2, y: CONTENT_TOP + (l.cardH - ARROW_H) / 2, w: ARROW_W, h: ARROW_H, fill: { color: C.accent2 }, line: { type: "none" }, objectName: `Arrow ${st.n} to ${st.n + 1}` });
		});
		const ry = CONTENT_TOP + l.cardH + GAP;
		const rowH = CONTENT_BOTTOM - ry;
		s.stats.forEach((st, i) => {
			statCard(slide, `Stat ${i + 1}`, st, CONTENT_X + i * (cardW + GAP), ry, cardW, rowH, l.statValuePt, l.statValueH, l.statLabelH);
		});
		const mx = CONTENT_X + s.stats.length * (cardW + GAP);
		const mw = CONTENT_X + CONTENT_W - mx;
		slide.addShape(R.roundRect, { x: mx, y: ry, w: mw, h: rowH, rectRadius: CARD_RADIUS, fill: { color: C.background2 }, line: { color: C.accent1, width: OUTLINE_PT * 2 }, objectName: "Message box" });
		iconBadge(slide, "Message icon", "list", mx + CARD_PAD, ry + (rowH - l.messageBadgeD) / 2, l.messageBadgeD, C.accent1);
		const mtx = mx + CARD_PAD + l.messageBadgeD + GAP_TIGHT;
		text(slide, "Key message", s.message, mtx, ry, mx + mw - CARD_PAD - mtx, rowH, { fontSize: BOX_MESSAGE_PT, bold: true, color: C.text2, valign: "middle" });
	};

	builders.manifest = (slide, s) => {
		title(slide, s.title);
		const m = MANIFEST;
		const n = s.columns.length;
		const colW = (CONTENT_W - (n - 1) * GAP) / n;
		const colsH = CONTENT_H - GAP - m.exampleBoxH;
		const icons = ["fileCode", "fileList"];
		s.columns.forEach((col, i) => {
			const x = CONTENT_X + i * (colW + GAP);
			card(slide, `Option ${i + 1} card`, x, CONTENT_TOP, colW, colsH);
			// Filled header block inset inside the card
			const hx = x + GAP_TIGHT / 2;
			const hy = CONTENT_TOP + GAP_TIGHT / 2;
			const hw = colW - GAP_TIGHT;
			slide.addShape(R.roundRect, { x: hx, y: hy, w: hw, h: m.headBarH, rectRadius: CARD_RADIUS, fill: { color: C.text2 }, line: { type: "none" }, objectName: `Option ${i + 1} header block` });
			iconBadge(slide, `Option ${i + 1} icon`, icons[i], hx + GAP_TIGHT / 2, hy + (m.headBarH - BADGE_SMALL_D) / 2, BADGE_SMALL_D, C.accent1);
			const tx = hx + GAP_TIGHT / 2 + BADGE_SMALL_D + GAP_TIGHT / 2;
			text(slide, `Option ${i + 1} head`, col.head, tx, hy, hx + hw - GAP_TIGHT / 2 - tx, m.headBarH, { fontFace: HEAD_FONT_REF, fontSize: m.headPt, bold: true, color: C.background1, valign: "middle" });
			const by = hy + m.headBarH + GAP_TIGHT;
			bullets(slide, `Option ${i + 1} points`, col.points, x + CARD_PAD, by, colW - 2 * CARD_PAD, CONTENT_TOP + colsH - CARD_PAD - by, { fontSize: m.bulletPt, paraSpacePt: PARA_SPACE_LOOSE_PT });
		});
		const ey = CONTENT_TOP + colsH + GAP;
		slide.addShape(R.roundRect, { x: CONTENT_X, y: ey, w: CONTENT_W, h: m.exampleBoxH, rectRadius: CARD_RADIUS, fill: { color: C.background2 }, line: { color: C.accent6, width: OUTLINE_PT }, objectName: "Example box" });
		iconBadge(slide, "Example icon", "fileAlt", CONTENT_X + GAP_TIGHT, ey + (m.exampleBoxH - m.exampleBadgeD) / 2, m.exampleBadgeD, C.accent2);
		const ex = CONTENT_X + GAP_TIGHT + m.exampleBadgeD + GAP_TIGHT;
		text(slide, "Pose-log example line", s.example, ex, ey, CONTENT_X + CONTENT_W - GAP_TIGHT - ex, m.exampleBoxH, { fontFace: MONO_FONT, fontSize: MONO_PT, color: C.text1, valign: "middle" });
	};

	builders.checks = (slide, s) => {
		title(slide, s.title);
		const k = CHECKS;
		const cols = 2;
		const rows = Math.ceil(s.cards.length / cols);
		const cardW = (CONTENT_W - (cols - 1) * GAP) / cols;
		const captionY = CONTENT_BOTTOM - k.captionH;
		const gridH = captionY - GAP - CONTENT_TOP;
		const cardH = (gridH - (rows - 1) * GAP) / rows;
		s.cards.forEach((c, i) => {
			const x = CONTENT_X + (i % cols) * (cardW + GAP);
			const y = CONTENT_TOP + Math.floor(i / cols) * (cardH + GAP);
			card(slide, `Check ${i + 1} card`, x, y, cardW, cardH, "white");
			iconBadge(slide, `Check ${i + 1} icon`, "warning", x + CARD_PAD, y + CARD_PAD, k.iconD, C.accent4);
			const tx = x + CARD_PAD + k.iconD + GAP_TIGHT;
			const tw = x + cardW - CARD_PAD - tx;
			text(
				slide,
				`Check ${i + 1} text`,
				[
					{ text: c.head, options: { fontSize: k.headPt, bold: true, color: C.text2, breakLine: true, paraSpaceAfter: PARA_SPACE_PT / 2 } },
					{ text: c.flag, options: { fontSize: k.flagPt, bold: true, color: C.accent1, breakLine: true, paraSpaceAfter: PARA_SPACE_PT / 2 } },
					{ text: c.text, options: { fontSize: k.textPt } },
				],
				tx,
				y + CARD_PAD,
				tw,
				cardH - 2 * CARD_PAD,
				{ valign: "top" }
			);
		});
		text(slide, "Checks caption", s.caption, CONTENT_X, captionY, CONTENT_W, k.captionH, { fontSize: CAPTION_PT, color: C.accent5, valign: "bottom" });
	};

	builders.independent = (slide, s) => {
		title(slide, s.title);
		const d = INDEPENDENT;
		const n = s.columns.length;
		const colW = (CONTENT_W - (n - 1) * GAP) / n;
		const colsH = CONTENT_H - GAP - d.messageH;
		s.columns.forEach((col, i) => {
			const x = CONTENT_X + i * (colW + GAP);
			card(slide, `Column ${i + 1} card`, x, CONTENT_TOP, colW, colsH);
			iconBadge(slide, `Column ${i + 1} icon`, col.icon, x + CARD_PAD, CONTENT_TOP + CARD_PAD, d.iconD, C.accent2);
			text(slide, `Column ${i + 1} head`, col.head, x + CARD_PAD + d.iconD + GAP_TIGHT, CONTENT_TOP + CARD_PAD, colW - 2 * CARD_PAD - d.iconD - GAP_TIGHT, d.iconD, { fontFace: HEAD_FONT_REF, fontSize: d.headPt, bold: true, color: C.text2, valign: "middle" });
			const by = CONTENT_TOP + CARD_PAD + d.iconD + GAP_TIGHT;
			bullets(slide, `Column ${i + 1} points`, col.points, x + CARD_PAD, by, colW - 2 * CARD_PAD, CONTENT_TOP + colsH - CARD_PAD - by, { fontSize: d.bulletPt, paraSpacePt: PARA_SPACE_LOOSE_PT });
		});
		const my = CONTENT_TOP + colsH + GAP;
		slide.addShape(R.roundRect, { x: CONTENT_X, y: my, w: CONTENT_W, h: d.messageH, rectRadius: CARD_RADIUS, fill: { color: C.background1 }, line: { color: C.accent4, width: OUTLINE_PT * 2 }, objectName: "Message box" });
		iconBadge(slide, "Message icon", "warning", CONTENT_X + CARD_PAD, my + (d.messageH - d.messageIconD) / 2, d.messageIconD, C.accent4);
		const mtx = CONTENT_X + CARD_PAD + d.messageIconD + GAP_TIGHT;
		text(slide, "Key message", s.message, mtx, my, CONTENT_X + CONTENT_W - CARD_PAD - mtx, d.messageH, { fontSize: BOX_MESSAGE_PT, bold: true, color: C.text2, valign: "middle" });
	};

	builders.spoilers = (slide, s) => {
		title(slide, s.title);
		const sp = SPOILERS;
		const colW = (CONTENT_W - (sp.columns - 1) * GAP) / sp.columns;
		const rowH = (CONTENT_H - (sp.rowsFirstColumn - 1) * GAP) / sp.rowsFirstColumn;
		const left = s.items.slice(0, sp.rowsFirstColumn);
		const right = s.items.slice(sp.rowsFirstColumn);
		[left, right].forEach((items, ci) => {
			rowList(slide, `Spoiler column ${ci + 1}`, items, {
				x: CONTENT_X + ci * (colW + GAP),
				y: CONTENT_TOP,
				w: colW,
				pt: sp.textPt,
				badgeD: sp.iconD,
				gap: GAP,
				minRowH: rowH,
				cardKind: "tint",
				cardPad: sp.cardPad,
				badge: (i, item) => ({ kind: "icon", icon: item.icon, fill: C.accent4 }),
			});
		});
	};

	builders.deliverables = (slide, s) => {
		title(slide, s.title);
		const d = DELIVERABLES;
		const listW = d.listW;
		rowList(slide, "Checklist", s.checklist, { x: CONTENT_X, y: CONTENT_TOP, w: listW, pt: d.textPt, badgeD: d.iconD, gap: GAP, minRowH: (CONTENT_H - (s.checklist.length - 1) * GAP) / s.checklist.length, cardKind: null, cardPad: 0, badge: () => ({ kind: "glyph", data: iconTealCheckSquare }) });
		const sx = CONTENT_X + listW + GAP;
		const sw = CONTENT_W - listW - GAP;
		card(slide, "Software card", sx, CONTENT_TOP, sw, CONTENT_H);
		iconBadge(slide, "Software icon", "code", sx + CARD_PAD, CONTENT_TOP + CARD_PAD, d.softwareIconD, C.accent2);
		text(slide, "Software head", s.software.head, sx + CARD_PAD + d.softwareIconD + GAP_TIGHT, CONTENT_TOP + CARD_PAD, sw - 2 * CARD_PAD - d.softwareIconD - GAP_TIGHT, d.softwareIconD, { fontFace: HEAD_FONT_REF, fontSize: d.headPt, bold: true, color: C.text2, valign: "middle" });
		const by = CONTENT_TOP + CARD_PAD + d.softwareIconD + GAP_TIGHT;
		bullets(slide, "Software points", s.software.points, sx + CARD_PAD, by, sw - 2 * CARD_PAD, CONTENT_TOP + CONTENT_H - CARD_PAD - by, { fontSize: d.bulletPt, paraSpacePt: PARA_SPACE_LOOSE_PT });
	};

	builders.next = (slide, s) => {
		title(slide, s.title);
		const nx = NEXT;
		const shareSum = nx.groupShares.reduce((a, b) => a + b, 0);
		const usable = CONTENT_W - (nx.groupShares.length - 1) * GAP;
		let x = CONTENT_X;
		const groups = [
			{ key: "open", head: EXTRA_LABELS.openHead, items: s.open, badge: () => ({ kind: "icon", icon: "question", fill: C.accent1 }) },
			{ key: "decided", head: EXTRA_LABELS.decidedHead, items: s.decided, badge: () => ({ kind: "icon", icon: "check", fill: C.accent2 }) },
			{ key: "steps", head: EXTRA_LABELS.stepsHead, items: s.steps, badge: (i) => ({ kind: "num", n: i + 1, fill: C.accent1 }) },
		];
		groups.forEach((g, gi) => {
			const w = (usable * nx.groupShares[gi]) / shareSum;
			card(slide, `${g.head} group card`, x, DARK_CONTENT_TOP, w, DARK_CONTENT_H, "dark");
			text(slide, `${g.head} group head`, g.head, x + CARD_PAD, DARK_CONTENT_TOP + CARD_PAD, w - 2 * CARD_PAD, nx.headH, { fontFace: HEAD_FONT_REF, fontSize: nx.headPt, bold: true, color: C.background1, valign: "middle" });
			rowList(slide, `${g.head} item`, g.items, { x: x + CARD_PAD, y: DARK_CONTENT_TOP + CARD_PAD + nx.headH + GAP_TIGHT, w: w - 2 * CARD_PAD, pt: nx.itemPt, badgeD: nx.iconD, gap: GAP_TIGHT, minRowH: nx.iconD + GAP_TIGHT, cardKind: null, cardPad: 0, textColor: C.background1, badge: g.badge, badgePt: SMALL_BADGE_NUM_PT });
			x += w + GAP;
		});
	};

	// ---- Assemble slides ---------------------------------------------------------------------
	let currentSection = null;
	for (const s of content.slides) {
		if (s.section !== currentSection) {
			pres.addSection({ title: s.section });
			currentSection = s.section;
		}
		const masterName = s.layout === "title_dark" ? "TITLE_DARK" : "TITLE_ONLY";
		const slide = pres.addSlide({ masterName, sectionTitle: s.section });
		const build = builders[s.id];
		if (!build) throw new Error(`No builder for slide id "${s.id}"`);
		build(slide, s);
		slide.addNotes(s.notes);
	}

	// ---- Write, then put the theme colors into the file ---------------------------------------
	await pres.writeFile({ fileName: OUTPUT_PPTX });
	await applyTheme(OUTPUT_PPTX, THEME);
	console.log("Wrote " + OUTPUT_PPTX);
}

main().catch((err) => {
	console.error(err);
	process.exit(1);
});
