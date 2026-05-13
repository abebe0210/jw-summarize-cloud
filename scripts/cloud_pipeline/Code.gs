const SYSTEM_COLUMNS = [
  "row_id",
  "status",
  "gcs_uri",
  "github_url",
  "error",
  "enqueued_at",
  "finished_at",
];

function onFormSubmit(e) {
  const sheet = e.range.getSheet();
  const rowNumber = e.range.getRow();
  const headers = ensureSystemColumns_(sheet);
  const rowId = Utilities.getUuid();

  setCell_(sheet, rowNumber, headers, "row_id", rowId);
  setCell_(sheet, rowNumber, headers, "status", "queued");
  setCell_(sheet, rowNumber, headers, "error", "");

  try {
    const sourceType = normalizeSourceType_(
      getCell_(sheet, rowNumber, headers, formColumn_("FORM_INPUT_TYPE_COLUMN", "入力種別"))
    );
    if (sourceType === "audio") {
      const gcsUri = copyAudioToGcs_(sheet, rowNumber, headers, rowId);
      setCell_(sheet, rowNumber, headers, "gcs_uri", gcsUri);
    }

    enqueueTask_(rowId, SpreadsheetApp.getActiveSpreadsheet().getId());
    setCell_(sheet, rowNumber, headers, "enqueued_at", nowJst_());
  } catch (error) {
    setCell_(sheet, rowNumber, headers, "status", "failed");
    setCell_(sheet, rowNumber, headers, "error", String(error && error.message ? error.message : error));
  }
}

function monitorQueuedRows() {
  const sheet = SpreadsheetApp.getActiveSheet();
  const headers = ensureSystemColumns_(sheet);
  const failedAfterMinutes = Number(scriptProperty_("FAILED_AFTER_MINUTES", "120"));
  const now = new Date();
  const values = sheet.getDataRange().getValues();

  for (let rowIndex = 1; rowIndex < values.length; rowIndex++) {
    const rowNumber = rowIndex + 1;
    const status = getRowValue_(values[rowIndex], headers, "status");
    const githubUrl = getRowValue_(values[rowIndex], headers, "github_url");
    const enqueuedAtRaw = getRowValue_(values[rowIndex], headers, "enqueued_at");
    if (status !== "queued" || githubUrl || !enqueuedAtRaw) {
      continue;
    }

    const enqueuedAt = new Date(enqueuedAtRaw);
    if (Number.isNaN(enqueuedAt.getTime())) {
      continue;
    }
    const elapsedMinutes = (now.getTime() - enqueuedAt.getTime()) / 60000;
    if (elapsedMinutes >= failedAfterMinutes) {
      setCell_(sheet, rowNumber, headers, "status", "failed");
      setCell_(
        sheet,
        rowNumber,
        headers,
        "error",
        `Timed out waiting for successful Cloud Run completion after ${failedAfterMinutes} minutes.`
      );
    }
  }
}

function installMonitorTrigger() {
  ScriptApp.newTrigger("monitorQueuedRows").timeBased().everyMinutes(15).create();
}

function copyAudioToGcs_(sheet, rowNumber, headers, rowId) {
  const audioColumn = formColumn_("FORM_AUDIO_COLUMN", "音声ファイル");
  const audioFileId = extractDriveFileId_(sheet, rowNumber, headers, audioColumn);
  if (!audioFileId) {
    throw new Error(`Missing Drive file id in column: ${audioColumn}`);
  }

  const file = DriveApp.getFileById(audioFileId);
  const blob = file.getBlob();
  const extension = extensionFromName_(file.getName());
  const objectName = `incoming/${rowId}${extension}`;
  const bucket = scriptProperty_("GCS_AUDIO_BUCKET");
  const url =
    `https://storage.googleapis.com/upload/storage/v1/b/${encodeURIComponent(bucket)}/o` +
    `?uploadType=media&name=${encodeURIComponent(objectName)}`;

  const response = UrlFetchApp.fetch(url, {
    method: "post",
    contentType: blob.getContentType(),
    payload: blob.getBytes(),
    headers: { Authorization: `Bearer ${ScriptApp.getOAuthToken()}` },
    muteHttpExceptions: true,
  });
  assertOk_(response, "GCS upload failed");
  file.setTrashed(true);
  return `gs://${bucket}/${objectName}`;
}

function enqueueTask_(rowId, sheetId) {
  const projectId = scriptProperty_("GCP_PROJECT_ID");
  const location = scriptProperty_("TASKS_LOCATION", "asia-northeast1");
  const queueName = scriptProperty_("TASKS_QUEUE_NAME", "jw-summarize-process");
  const cloudRunUrl = scriptProperty_("CLOUD_RUN_PROCESS_URL");
  const audience = scriptProperty_("CLOUD_RUN_AUDIENCE", cloudRunUrl);
  const serviceAccountEmail = scriptProperty_("CLOUD_TASKS_SERVICE_ACCOUNT");
  const dispatchDeadlineSeconds = Number(
    scriptProperty_("TASK_DISPATCH_DEADLINE_SECONDS", "1800")
  );
  const endpoint =
    `https://cloudtasks.googleapis.com/v2/projects/${projectId}` +
    `/locations/${location}/queues/${queueName}/tasks`;
  const body = {
    task: {
      dispatchDeadline: `${dispatchDeadlineSeconds}s`,
      httpRequest: {
        httpMethod: "POST",
        url: cloudRunUrl,
        headers: { "Content-Type": "application/json" },
        body: Utilities.base64Encode(JSON.stringify({ row_id: rowId, sheet_id: sheetId })),
        oidcToken: {
          serviceAccountEmail,
          audience,
        },
      },
    },
  };

  const response = UrlFetchApp.fetch(endpoint, {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(body),
    headers: { Authorization: `Bearer ${ScriptApp.getOAuthToken()}` },
    muteHttpExceptions: true,
  });
  assertOk_(response, "Cloud Tasks enqueue failed");
}

function ensureSystemColumns_(sheet) {
  const lastColumn = sheet.getLastColumn();
  const headers = sheet.getRange(1, 1, 1, lastColumn).getValues()[0].map(String);
  const headerMap = {};
  headers.forEach((name, index) => {
    if (name) {
      headerMap[name] = index + 1;
    }
  });

  SYSTEM_COLUMNS.forEach((name) => {
    if (!headerMap[name]) {
      const column = sheet.getLastColumn() + 1;
      sheet.getRange(1, column).setValue(name);
      headerMap[name] = column;
    }
  });
  return headerMap;
}

function getCell_(sheet, rowNumber, headers, columnName) {
  const column = headers[columnName];
  if (!column) {
    return "";
  }
  return String(sheet.getRange(rowNumber, column).getValue()).trim();
}

function getRowValue_(rowValues, headers, columnName) {
  const column = headers[columnName];
  if (!column) {
    return "";
  }
  return String(rowValues[column - 1] || "").trim();
}

function setCell_(sheet, rowNumber, headers, columnName, value) {
  const column = headers[columnName];
  if (!column) {
    throw new Error(`Missing column: ${columnName}`);
  }
  sheet.getRange(rowNumber, column).setValue(value);
}

function extractDriveFileId_(sheet, rowNumber, headers, columnName) {
  const column = headers[columnName];
  if (!column) {
    return null;
  }
  const range = sheet.getRange(rowNumber, column);
  const richText = range.getRichTextValue();
  const linkUrl = richText && richText.getLinkUrl();
  return parseDriveFileId_(linkUrl || String(range.getValue()));
}

function parseDriveFileId_(value) {
  if (!value) {
    return null;
  }
  const patterns = [
    /\/file\/d\/([A-Za-z0-9_-]+)/,
    /[?&]id=([A-Za-z0-9_-]+)/,
    /^([A-Za-z0-9_-]{25,})$/,
  ];
  for (const pattern of patterns) {
    const match = String(value).match(pattern);
    if (match) {
      return match[1];
    }
  }
  return null;
}

function normalizeSourceType_(value) {
  const normalized = String(value || "").trim().toLowerCase();
  const aliases = {
    url: "url",
    "動画url": "url",
    "動画 url": "url",
    text: "text",
    "本文": "text",
    "テキスト": "text",
    audio: "audio",
    "音声": "audio",
    "音声ファイル": "audio",
  };
  const sourceType = aliases[normalized];
  if (!sourceType) {
    throw new Error(`Unsupported source type: ${value}`);
  }
  return sourceType;
}

function extensionFromName_(name) {
  const match = String(name || "").match(/\.[A-Za-z0-9]+$/);
  return match ? match[0].toLowerCase() : ".mp3";
}

function formColumn_(propertyName, defaultValue) {
  return scriptProperty_(propertyName, defaultValue);
}

function scriptProperty_(name, defaultValue) {
  const value = PropertiesService.getScriptProperties().getProperty(name);
  if (value) {
    return value;
  }
  if (defaultValue !== undefined) {
    return defaultValue;
  }
  throw new Error(`Missing script property: ${name}`);
}

function nowJst_() {
  return Utilities.formatDate(new Date(), "Asia/Tokyo", "yyyy-MM-dd'T'HH:mm:ssXXX");
}

function assertOk_(response, message) {
  const code = response.getResponseCode();
  if (code < 200 || code >= 300) {
    throw new Error(`${message}: HTTP ${code} ${response.getContentText()}`);
  }
}
