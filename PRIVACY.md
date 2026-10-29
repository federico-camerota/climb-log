# Privacy policy

climb-log is a free, open-source app (GPL-3.0-or-later) for logging and analysing climbing
training. You run it on your own computer, and it works only with data you own. This policy
covers the app as published in this repository. Last updated 2026-10-29.

## What the app does with your data
- **It runs on your computer.** The app is a local web server, reachable from your machine
  only. Nobody else, including the developers, operates a server for it or receives any of your
  data.
- **Your data stays in your spreadsheets.** Training records live in local `.xlsx` files or in
  Google Sheets in your own Google account. The app also keeps local copies on your computer: a
  snapshot of the data for fast loading, and backups.
- **No telemetry, analytics or advertising.** The app sends nothing about you or your use of it
  anywhere.

## Google user data
When you connect a module to Google Sheets, you log in with an OAuth client that you create in
your own Google Cloud project, and you grant the app two permissions:

- **Google Sheets** (`https://www.googleapis.com/auth/spreadsheets`): to read and write the
  spreadsheets that hold your training journals.
- **Google Drive, files the app creates** (`https://www.googleapis.com/auth/drive.file`): to see
  when those spreadsheets change and to export backup copies of them. The app cannot see your
  other Drive files.

The app uses this access only to show, record and analyse your own training data, at your
request. Data read from Google is stored only on your computer (snapshots and backups, as above).
It is never sent to any other service, sold, shared with anyone, or used for advertising, and no
human other than you reads it. climb-log's use of information received from Google APIs adheres
to the [Google API Services User Data
Policy](https://developers.google.com/terms/api-services-user-data-policy), including the
Limited Use requirements.

The login token is saved on your computer, readable by your user account only, and is never
printed or logged. `climblog google logout` revokes the app's access and deletes the token; you
can also remove the access at any time at
[myaccount.google.com/permissions](https://myaccount.google.com/permissions).

## Deleting your data
Everything the app stores is on your computer or in your own spreadsheets: delete the
spreadsheets, the app's snapshot and backup folders (by default under
`~/.local/share/climblog/`) and the config folder (`~/.config/climblog/`).

## Contact
Questions or changes to this policy: open an issue at
[github.com/federico-camerota/climb-log](https://github.com/federico-camerota/climb-log/issues).
Changes are made through the repository, so its history shows every version of this policy.
