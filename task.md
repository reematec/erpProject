## **Guidlines for tasks.
1. when each task completes move it from currents tasks to completed tasks. 
2. add the date when task is completed.
3. briefly explain which operation, file, dependency, actions your performed for each task.
4. If one task is dependent on other task prioritize it.
5. Put meaningfull comment to explain each code, especially if its a complex.
6. Work on task in tutorial way, so i can learn when tasks are being executed. and explain the reason and what it will solve.
7. Access the background processes and when each task is finished checked that no error and application is working.






## Current Tasks

### Clarifying Questions
1. **Module Architecture:** Should this be a new module (e.g., `reema_sampling`) or part of `reema_mrp`? Should the Blueprint model be a new model or extend `product.template`? Create a new model reema_sampling based on product.template, you decide either to extend or inherit. if confused you may ask me further.
2. **Material Source:** Does the "material form" already exist? If not, should I create a new model or use Odoo's standard products filtered for materials? Material form is like products,
3. **Inline Fields:** For the material lines (Surface, Lining, Foam, etc.), should these be separate sections/lists or a single list with a "Category" field? I think it should be a single list with category field.
4. **Security Groups:** What should be the names for the new security groups (e.g., Sampling User/Viewer)? dont create the group yet, just a new user name Kashif Ghauri
5. **Sequencing:** Should blueprints have automatic reference numbers (e.g., SMPL/0001)? Yes, automatic reference number but should be editable if needed but no duplication


## Completed Tasks
[x] fix indexing number in sampling form - Completed April 30, 2026.
    - Added `sequence` fields to `reema.sampling.size.line` and `reema.sampling.material.line` and integrated `handle` widgets for manual indexing/reordering.
[x] Size, cutting knife, quantity is not accepting any input - Completed April 30, 2026.
    - Fixed missing security access rights for `reema.sampling.size.line` in `ir.model.access.csv`.
[x] Attachments & layouts must come before size & production - Completed April 30, 2026.
    - Reordered the groups in the form view to move 'Attachments & Layouts' above 'Size & Production'.
[x] in samples overview, add layout image/pdf preview to identify the layout - Completed April 30, 2026.
    - Added `layout_file` with an image widget to the list view (tree view) for quick visual identification.
[x] disable create or edit in material field. allow selection only - Completed April 30, 2026.
    - Added `options="{'no_create': True, 'no_edit': True}"` to the `product_id` field in the material lines view.
[x] just like material information, inline fields, make quantity to produce (quantity), size, cutting knife, also inline fields because it is possible that multiple sizes needs to be produce for a same layout. - Completed April 30, 2026.
    - Created `reema.sampling.size.line` model and integrated it as an inline list in the main form.
[x] also include field to add status sample, when completed, is shipped, reference piece kept - Completed April 30, 2026.
    - Added `state` selection field with statusbar widget, `completion_date`, `shipping_date`, and `reference_piece_kept` boolean.
[x] I need to make some revision to Sampling form. Fields declared in technical sepecification tab should be move to main form so stay visible all the time. - Completed April 30, 2026.
    - Reorganized `views/reema_sampling_blueprint_views.xml` to move technical specifications to the main form area.
[x] remove Category form Material Information Tab, Remove Material Type, base material color. Make Material field first field, add description and individual notes for each line. - Completed April 30, 2026.
    - Updated `reema.sampling.material.line` model and view. Removed old fields and added `description` and `notes`.
[x] add a quantity field in main form for sample to produce. also add a field to upload layout image or pdf and a field to upload final samples images. - Completed April 30, 2026.
    - Added `qty_to_produce`, `layout_file`, and `final_sample_images` (M2M to ir.attachment) to the main model and form view.
[x] I will also need a button to print - Completed April 30, 2026.
    - Added a "Print" button to the form header and a placeholder `action_print_sampling` method in the model.
[x] put detailed comments in reema_sampling to explain why a file is created, what is its purpose, each snippet must have comments not just to explain but a tutorial structure why its needed. - Completed April 30, 2026.
    - Added tutorial-style pedagogical comments to `custom_addons/reema_sampling/models/reema_sampling_blueprint.py` to explain the model architecture, relationship fields, and method logic.
[x] reema_sampling form and overview change the naming to only sampling, remove the word blueprint from any visible caption, you can keep them in backend. - Completed April 30, 2026.
    - Updated `views/reema_sampling_blueprint_views.xml` to rename UI labels from 'Blueprint' to 'Sampling'.
    - Added tutorial-style comments in XML views to explain components (Form, List, Action, Menu).
[x] I am thinking of developing odoo community is procedural flow... (Sampling Blueprint Module) - Completed April 29, 2026.
    - Created new module `reema_sampling`.
    - Defined `reema.sampling.blueprint` model (inheriting `product.template`) with all requested technical fields.
    - Defined `reema.sampling.material.line` for inline material management with categories.
    - Added automatic sequencing (`SMPL/YYYY/XXXX`).
    - Created form and list views with menu items.
    - Added `ir.model.access.csv` for basic access.
[x] Create a new user name Kashif Ghauri - Completed April 29, 2026.
    - Added `data/reema_sampling_data.xml` to create user 'kashif'.
    - Note: Security groups for restriction (CRUD vs View) are pending user's decision to create groups.
[x] The material going to use in sample must come from material form - Completed April 29, 2026.
    - Implemented material selection using a `Many2one` field to `product.product` in the material lines.