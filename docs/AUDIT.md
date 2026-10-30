# Audit trail

Owner: Grace (Finance). Changes need Finance sign-off (see CODEOWNERS).

`hl_log.audit()` appends to `audit.log`. That file is our record of invoices issued, and it's exported monthly to our accountants and kept for HMRC for 6 years. The accountants' import parses the pipe-separated format exactly:

    <ts>|<service>|<action>|<key>=<value>|...

Don't change the format, the path, or which actions are written. This trail isn't application logging, and it isn't part of the log pipeline.
