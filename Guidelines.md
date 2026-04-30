### 1. The "Simple & Safe" Coding Guidelines
These rules force the AI to write code that is easy for you to manage, even if you aren't a programmer.

* **Standard First:** "Always use Odoo standard fields and functions (ORM) before writing custom Python logic. If Odoo has a built-in way to do it, use that."
* **No "Fancy" Code:** "Avoid decorators, complex generators, or deep nested loops. Use simple `if/else` statements and `for` loops so a human can read the logic."
* **Security by Design:** "Every new model must have an `ir.model.access.csv` file. Never use `sudo()` unless absolutely necessary for a background process, and explain why it was used."
* **Self-Healing Logic:** "Include 'Checkers.' For example, before creating a Vendor Bill for a contractor, check if the Piece-Rate for that Hall is greater than zero. If not, log a warning and stop."
* **Background Safety:** "If a task takes longer than 2 seconds (like generating 100 bills at once), use a `Scheduled Action` (Cron) so the screen doesn't freeze for Ali Shan."

---

### 2. The "Task Completion" Reporting Template
To keep you from getting lost, tell the AI to use this exact format every time it finishes a task:

> **[TASK STATUS: COMPLETED]**
> * **Task Name:** (e.g., Phase 2.1: Piece-Rate Model)
> * **What changed?** (List files created or modified)
> * **How it works:** (Explain in plain English, e.g., "I created a table where you can type the price for each hall.")
> * **Dependencies:** (What other Odoo apps does this need? e.g., "Needs 'Accounting' module to be installed.")
> * **Verification:** (Where should I click in Odoo to see if this worked?)
> * **Console Check:** (Confirming no errors in the WSL terminal or Browser console.)

---

### 3. Guidelines to Avoid "Closed Alleys"
Since you don't know Python, these rules prevent the AI from giving you code you can't fix:

* **The "Comment Everything" Rule:** "Comment every 3 lines of code in English. Tell me what that specific block is doing for the business (e.g., # This part multiplies balls by the PKR rate)."
* **The "One-at-a-Time" Rule:** "Do not give me code for two tasks at once. Give me the code for Task A, wait for me to test it, and only then move to Task B."
* **No "Silent Failures":** "If the code hits an error, make it pop up a 'User Error' message in Odoo that tells me exactly what is missing (e.g., 'Error: No contractor selected')."
* **Naming Convention:** "Use business names for variables. Use `contractor_rate` instead of `x_rate`. Use `hall_number` instead of `loc_id`."

---

### 4. How to Use These Guidelines with the CLI
When you start a session in your WSL terminal, paste this:

> "I am Muhammad Amir. I am non-technical. You must follow the **'Reema Protocol'** for all coding:
> 1. Use simple Odoo 18 ORM code only.
> 2. Document every completion using my reporting template.
> 3. Verify security (CSV files) for every new model.
> 4. Check the WSL console for 'Python Traceback' errors before telling me it is done.
> 
> Let's start with Task 1.1: Module Scaffolding."

