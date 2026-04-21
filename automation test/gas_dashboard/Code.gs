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

  // Fetch opportunities (NORAM filter applied server-side)
  const opps = fetchOpportunities_(instanceUrl, accessToken);

  if (opps.length === 0) {
    return JSON.stringify({ opportunities: [], fieldHistory: [], fetchedAt: new Date().toISOString() });
  }

  // Fetch field history for all returned opps
  const oppIds   = opps.map(o => o.Id);
  const history  = fetchFieldHistory_(instanceUrl, accessToken, oppIds);

  return JSON.stringify({
    opportunities: opps,
    fieldHistory:  history,
    fetchedAt:     new Date().toISOString()
  });
}

// ----------------------------------------------------------------------------
// Opportunity query  — NORAM OR logic applied in SOQL
// ----------------------------------------------------------------------------

function fetchOpportunities_(instanceUrl, accessToken) {
  const soql = [
    'SELECT Id, Name, Type, StageName, Sub_Stage__c,',
    '  Account_Territory__c, Record_Owner_Sales_Territory__c,',
    '  Second_Opp_Owner_Sales_Territory__c, Acquiring_Channel__c,',
    '  CreatedDate, CloseDate, Date_MAF_Submitted_By_Merchant__c,',
    '  Owner.Name, OwnerId, Amount, Account.Name',
    'FROM Opportunity',
    'WHERE Type = \'New Business\'',
    'AND (',
    '  Account_Territory__c LIKE \'%NORAM%\'',
    '  OR Record_Owner_Sales_Territory__c LIKE \'%NORAM%\'',
    '  OR Second_Opp_Owner_Sales_Territory__c LIKE \'%NORAM%\'',
    '  OR Acquiring_Channel__c = \'CRB(US)\'',
    ')',
    'ORDER BY CreatedDate DESC'
  ].join(' ');

  return sfFetchAll_(instanceUrl, accessToken, soql);
}

// ----------------------------------------------------------------------------
// Field history query — sub_stage movements
// ----------------------------------------------------------------------------

function fetchFieldHistory_(instanceUrl, accessToken, oppIds) {
  if (!oppIds || oppIds.length === 0) return [];

  const allHistory = [];
  const batchSize  = 400; // SOQL IN clause practical limit

  for (let i = 0; i < oppIds.length; i += batchSize) {
    const batch  = oppIds.slice(i, i + batchSize);
    const idList = batch.map(id => "'" + id + "'").join(',');
    const soql   = [
      'SELECT OpportunityId, Field, OldValue, NewValue, CreatedDate',
      'FROM OpportunityFieldHistory',
      "WHERE Field IN ('Sub_Stage__c', 'Sub-Stages', 'StageName')",
      'AND OpportunityId IN (' + idList + ')',
      'ORDER BY CreatedDate ASC'
    ].join(' ');

    const records = sfFetchAll_(instanceUrl, accessToken, soql);
    records.forEach(r => allHistory.push(r));
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
        'SF_ACCESS_TOKEN has expired. Update it in Script Properties:\n' +
        'Extensions → Apps Script → Project Settings → Script Properties'
      );
    }
    if (code !== 200) {
      throw new Error('Salesforce API error ' + code + ': ' +
                      resp.getContentText().substring(0, 400));
    }

    const data = JSON.parse(resp.getContentText());
    (data.records || []).forEach(r => records.push(r));

    url = (!data.done && data.nextRecordsUrl)
          ? instanceUrl + data.nextRecordsUrl
          : null;
  }

  return records;
}
