# Project template

Copy this folder to start a new project:

```
cp -R templates/project projects/<project-name>
```

Then:

1. **Repository.** Create an empty git repo with one commit on `main`, e.g.
   `mkdir ~/code/<project-name> && cd ~/code/<project-name> && git init -b main && git commit --allow-empty -m "Start"`
2. **project.yaml.** Set `name` (the folder name) and `workspace` (the repo path).
3. **The first unit.** Rename `services/app` to your unit's name (lowercase, digits,
   hyphens), and edit its `unit.yaml`: description, packaging and the technical defaults.
4. **Tickets.** In `services/<unit>/tickets/batch-1/`, edit `001-example.yaml` and
   copy it for more tickets (`002-...yaml`, ...). Replace every TODO; the gate
   refuses any ticket that still contains one.
5. **Check, then run.**

   ```
   .venv/bin/python core/ticket_check/dor_check.py projects/<project-name>/services/<unit>/tickets/batch-1
   .venv/bin/python core/runner/run_batch.py projects/<project-name>/services/<unit>/tickets/batch-1
   ```

**More units.** Copy `services/app` to `services/<other-unit>` for each service.
For an integration, rename `integrations/_local` to drop the underscore (folders
starting with `_` are ignored) and list the services it connects. Delete what you
don't need: a single-service project needs nothing but `project.yaml` and one unit.

**Later batches.** Add `tickets/batch-2/` and so on. Ticket ids must be unique
across the whole project.

This README is ignored by the factory; delete it or keep it.
