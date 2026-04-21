// ============================================================================
// NORAM Sales Velocity Dashboard — Google Apps Script
// ============================================================================
// Setup: Project Settings → Script Properties → add:
//   SF_INSTANCE_URL  = https://checkout.my.salesforce.com
//   SF_ACCESS_TOKEN  = <your sid token>
// Deploy: Deploy → New Deployment → Web App → Execute as Me → Access: Anyone
// ============================================================================

const PROPS = PropertiesService.getScriptProperties();
const SF_API_VERSION = 'v59.0';

// ----------------------------------------------------------------------------
// Entry point
// ----------------------------------------------------------------------------

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('NORAM Sales Velocity Dashboard')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

// ----------------------------------------------------------------------------
// Main data function — called by client via google.script.run
// ----------------------------------------------------------------------------

function getSalesforceData() {
  const instanceUrl = PROPS.getProperty('SF_INSTANCE_URL');
  const accessToken = PROPS.getProperty('SF_ACCESS_TOKEN');

  if (!instanceUrl || !accessToken) {
    throw new Error(
      'Script Properties not configured.\n' +
      'Go to: Extensions → Apps Script → Project Settings → Script Properties\n' +
      'Add: SF_INSTANCE_URL and SF_ACCESS_TOKEN'
    );
  }

  // Discover which optional custom fields actually exist in this org
  const knownFields = discoverOptionalFields_(instanceUrl, accessToken);

  const opps = fetchOpportunities_(instanceUrl, accessToken, knownFields);

  if (opps.length === 0) {
    return JSON.stringify({
      opportunities: [], fieldHistory: [],
      knownFields:   knownFields,
      fetchedAt:     new Date().toISOString()
    });
  }

  const oppIds = opps.map(o => o.Id);
  const history = fetchFieldHistory_(instanceUrl, accessToken, oppIds, knownFields);

  return JSON.stringify({
    opportunities: opps,
    fieldHistory:  history,
    knownFields:   knownFields,
    fetchedAt:     new Date().toISOString()
  });
}

// ----------------------------------------------------------------------------
// Field discovery — checks which optional custom fields exist
// ----------------------------------------------------------------------------

// Fields we'd like to use but that may not exist in every org.
// Maps our internal key → array of candidate API names to try (first match wins).
const OPTIONAL_FIELDS = {
  subStage:   ['Sub_Stage__c', 'Sub_Stages__c', 'SubStage__c', 'Stage_Detail__c'],
  mafDate:    ['Date_MAF_Submitted_By_Merchant__c', 'MAF_Submitted_Date__c', 'MAF_Date__c'],
  territory:  ['Account_Territory__c', 'Territory__c'],
  ownerTerritory: ['Record_Owner_Sales_Territory__c', 'Owner_Sales_Territory__c'],
  secondTerritory:['Second_Opp_Owner_Sales_Territory__c', 'Second_Owner_Territory__c'],
  channel:    ['Acquiring_Channel__c', 'Channel__c'],
};

function discoverOptionalFields_(instanceUrl, accessToken) {
  // Describe the Opportunity object to get all field API names
  const url = instanceUrl + '/services/data/' + SF_API_VERSION +
              '/sobjects/Opportunity/describe';
  const resp = UrlFetchApp.fetch(url, {
    headers: { 'Authorization': 'Bearer ' + accessToken },
    muteHttpExceptions: true
  });

  if (resp.getResponseCode() !== 200) {
    // Can't describe — return empty so we skip all optional fields safely
    return {};
  }

  const meta       = JSON.parse(resp.getContentText());
  const fieldNames = new Set(meta.fields.map(f => f.name));
  const resolved   = {};

  for (const [key, candidates] of Object.entries(OPTIONAL_FIELDS)) {
    const match = candidates.find(c => fieldNames.has(c));
    if (match) resolved[key] = match;
  }

  return resolved;
}

// ----------------------------------------------------------------------------
// Opportunity query — NORAM OR logic; only selects fields that exist
// ----------------------------------------------------------------------------

function fetchOpportunities_(instanceUrl, accessToken, knownFields) {
  const kf = knownFields;

  // Build SELECT clause — always include standard fields, add discovered optionals
  const selectFields = [
    'Id', 'Name', 'Type', 'StageName',
    'CreatedDate', 'CloseDate',
    'Owner.Name', 'OwnerId', 'Amount', 'Account.Name',
  ];
  if (kf.subStage)        selectFields.push(kf.subStage);
  if (kf.mafDate)         selectFields.push(kf.mafDate);
  if (kf.territory)       selectFields.push(kf.territory);
  if (kf.ownerTerritory)  selectFields.push(kf.ownerTerritory);
  if (kf.secondTerritory) selectFields.push(kf.secondTerritory);
  if (kf.channel)         selectFields.push(kf.channel);

  // Build WHERE — NORAM filter using whichever territory/channel fields exist
  const noramClauses = [];
  if (kf.territory)       noramClauses.push(kf.territory       + " LIKE '%NORAM%'");
  if (kf.ownerTerritory)  noramClauses.push(kf.ownerTerritory  + " LIKE '%NORAM%'");
  if (kf.secondTerritory) noramClauses.push(kf.secondTerritory + " LIKE '%NORAM%'");
  if (kf.channel)         noramClauses.push(kf.channel         + " = 'CRB(US)'");

  // Fallback: if none of the territory fields exist, just pull New Business opps
  const whereClause = noramClauses.length > 0
    ? "Type = 'New Business' AND (" + noramClauses.join(' OR ') + ')'
    : "Type = 'New Business'";

  const soql = 'SELECT ' + selectFields.join(', ') +
               ' FROM Opportunity WHERE ' + whereClause +
               ' ORDER BY CreatedDate DESC';

  return sfFetchAll_(instanceUrl, accessToken, soql);
}

// ----------------------------------------------------------------------------
// Field history — tries Sub_Stage__c label variants + StageName
// ----------------------------------------------------------------------------

function fetchFieldHistory_(instanceUrl, accessToken, oppIds, knownFields) {
  if (!oppIds || oppIds.length === 0) return [];

  // Build the field name list for the WHERE clause
  const fieldNames = ["'StageName'", "'Sub-Stages'"];
  if (knownFields.subStage) fieldNames.push("'" + knownFields.subStage + "'");

  const allHistory = [];
  const batchSize  = 400;

  for (let i = 0; i < oppIds.length; i += batchSize) {
    const batch  = oppIds.slice(i, i + batchSize);
    const idList = batch.map(id => "'" + id + "'").join(',');
    const soql   = [
      'SELECT OpportunityId, Field, OldValue, NewValue, CreatedDate',
      'FROM OpportunityFieldHistory',
      'WHERE Field IN (' + fieldNames.join(',') + ')',
      'AND OpportunityId IN (' + idList + ')',
      'ORDER BY CreatedDate ASC'
    ].join(' ');

    try {
      const records = sfFetchAll_(instanceUrl, accessToken, soql);
      records.forEach(r => allHistory.push(r));
    } catch (e) {
      // If field history query fails, continue without it
      console.error('Field history batch failed: ' + e.message);
    }
  }

  return allHistory;
}

// ----------------------------------------------------------------------------
// Paginated SF REST query helper
// ----------------------------------------------------------------------------

function sfFetchAll_(instanceUrl, accessToken, soql) {
  const headers = { 'Authorization': 'Bearer ' + accessToken };
  const records = [];

  let url = instanceUrl + '/services/data/' + SF_API_VERSION +
            '/query?q=' + encodeURIComponent(soql);

  while (url) {
    const resp = UrlFetchApp.fetch(url, { headers: headers, muteHttpExceptions: true });
    const code = resp.getResponseCode();

    if (code === 401) {
      throw new Error(
        'SF_ACCESS_TOKEN has expired.\n' +
        'Get a fresh sid cookie from DevTools → checkout.my.salesforce.com\n' +
        'and update SF_ACCESS_TOKEN in Script Properties.'
      );
    }
    if (code !== 200) {
      throw new Error('Salesforce API error ' + code + ': ' +
                      resp.getContentText().substring(0, 500));
    }

    const data = JSON.parse(resp.getContentText());
    (data.records || []).forEach(r => records.push(r));

    url = (!data.done && data.nextRecordsUrl)
          ? instanceUrl + data.nextRecordsUrl
          : null;
  }

  return records;
}
