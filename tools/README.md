# Certification Harness Tools

## Commands

```bash
# Generate old tool baselines
python tools/old_tool_runner.py --csv data/raw/OK_R1.csv --config tools/batch_configs/OK_R1.json --output audit/baselines/old_tool/OK_R1.json

# Generate all 3 baselines at once
python tools/old_tool_runner.py --all

# Run parity check (webapp vs baseline)
python tools/parity_check.py --baseline audit/baselines/old_tool/OK_R1.json --webapp audit/baselines/webapp/OK_R1.json

# Generate PDF report
python tools/generate_report_pdf.py

# Run next pending cycle
python tools/cycle_runner.py --next

# Run a specific cycle
python tools/cycle_runner.py --cycle 1 --feature F-0001
```

## Test Accounts

| Email | Tier | Password |
|-------|------|----------|
| theos.elive@gmail.com | demo | claudetest |
| theo.stipapro@gmail.com | racer | claudetest |
| fsae.ecn@gmail.com | world_class | claudetest |

## Parity Tolerances

| Metric | Tolerance |
|--------|-----------|
| Lap times | +/-0.001s |
| Speeds | +/-0.01 m/s |
| Scores | +/-0.5 points |
| GPS coordinates | +/-0.0001 deg |
| Percentages | +/-0.1% |
