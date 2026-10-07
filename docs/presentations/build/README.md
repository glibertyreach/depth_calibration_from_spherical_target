# Building the stage-1 decks

`make_stage1_deck.js` builds two decks from two content files (all slide text
and speaker notes) and the figure panels in `../assets/`:

| Content file | Deck |
|---|---|
| `stage1_build_deck_content.json` | `../stage1_procurement_build.pptx` (10 slides) |
| `stage1_procedure_deck_content.json` | `../stage1_test_procedure.pptx` (14 slides) |

Edit a JSON to change wording; edit the constants at the top of the script to
change layout, sizes or colors. Figure pixel sizes are read when the script
runs, so a re-cropped figure needs no code change.

1. Install the Node dependencies once, in this folder: `npm install`
2. From the repository root, build both decks:

   ```
   NODE_PATH=docs/presentations/build/node_modules \
   PPTX_SKILL_SCRIPTS=<folder holding apply_theme.js> \
       node docs/presentations/build/make_stage1_deck.js
   ```

   or one deck, giving the content file and the output file:

   ```
   NODE_PATH=docs/presentations/build/node_modules \
   PPTX_SKILL_SCRIPTS=<folder holding apply_theme.js> \
       node docs/presentations/build/make_stage1_deck.js \
           docs/presentations/build/stage1_procedure_deck_content.json \
           docs/presentations/stage1_test_procedure.pptx
   ```

3. Check the text: `python3 docs/presentations/archive/check_stage1_content.py`
   compares both decks with their JSON files (every string on its slide,
   notes equal to the JSON notes) and must report 0 problems.

`apply_theme.js` comes from the pptx skill used to write this generator; it
writes the theme's colors and fonts into the finished file. The script needs
it to run: point `PPTX_SKILL_SCRIPTS` at the folder holding a copy, or keep
the script's default path.

The figure panels in `../assets/` are crops of the procedure's figures in
`docs/procedures/figures/`; regenerate those first if a figure changes.
Render checks and intermediate files go in `../archive/`.
