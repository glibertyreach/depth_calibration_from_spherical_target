# Building the stage-1 overview deck

`make_stage1_deck.js` builds `../stage1_capture_overview.pptx` from
`stage1_deck_content.json` (all slide text and speaker notes) and the figure
panels in `../assets/`. Edit the JSON to change wording; edit the constants at
the top of the script to change layout, sizes or colors.

1. Install the Node dependencies once, in this folder: `npm install`
2. From the repository root:

   ```
   NODE_PATH=docs/presentations/build/node_modules \
   PPTX_SKILL_SCRIPTS=<folder holding apply_theme.js> \
       node docs/presentations/build/make_stage1_deck.js
   ```

`apply_theme.js` comes from the pptx skill used to write this generator; it
writes the theme's colors and fonts into the finished file. The script needs
it to run: point `PPTX_SKILL_SCRIPTS` at the folder holding a copy, or keep
the script's default path.

The figure panels in `../assets/` are crops of the procedure's figures in
`docs/procedures/figures/`; regenerate those first if a figure changes.
Render checks and intermediate files go in `../archive/`.
