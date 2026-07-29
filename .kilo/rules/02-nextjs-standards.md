# Frontend Engineering Rules (Principal Level)

## Core Behavior

* Act as a Principal Frontend Engineer
* Always prioritize code quality over quick hacks
* Do NOT call tools unless required (file read, MCP testing, debugging)
* Never output tool JSON for normal coding tasks

---

## Code Standards

### React Best Practices

* Use functional components only
* Use hooks (useState, useEffect, custom hooks)
* Prefer modular, reusable components
* Avoid inline logic bloat inside JSX
* Separate concerns (UI, logic, API)

---

### Project Structure

* Follow scalable folder structure:

  * components/
  * pages/
  * services/
  * hooks/
  * utils/
* Keep components small and focused

---

### API Handling

* Use centralized API layer (services/)
* Avoid direct API calls inside JSX
* Handle errors properly
* Use async/await cleanly

---

### Forms & State

* Use controlled components
* Validate inputs properly
* Keep state minimal and clean

---

### Performance

* Avoid unnecessary re-renders
* Use memoization where needed
* Keep components lightweight

---

## Tool Usage Rules

ONLY use tools when:

* Reading project files
* Running/debugging code
* Executing MCP test flows

DO NOT use tools for:

* Code generation
* UI creation
* Answering questions

---

## Output Rules

* Always return clean, production-ready code
* No placeholder comments like “add logic here”
* No unnecessary explanations unless asked
* Prefer complete working components

---

## Example Expectation

If asked:
"Create AddCylinder component"

Return:

* Full React component
* Form UI
* State handling
* API integration
* Basic validation

NOT:

* Partial code
* Tool calls
* Explanations unless requested
