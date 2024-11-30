
// Google Apps Script that executes every time someone fill the form (a new entry to google sheets)

function onFormSubmit(e) {
  Logger.log(JSON.stringify(e));
  const formResponse = e.values[2];
  const webhookUrl = ""; // Replace with your Discord webhook URL
  // 5. Send the message to Discord

  let auto_approve_url = "https://streamsnip.com/autoapprove?key="+formResponse+"&value="+e.values[3]+"&email="+e.values[1]+"&proof="+e.values[4];
  Logger.log(auto_approve_url);
  let aaoptions = {
    method: "GET",
  }
  let aaresponse = UrlFetchApp.fetch(auto_approve_url, aaoptions);


  let payload = JSON.stringify({
    content: `New Form Submission For: <${formResponse}> \nAutoApprove ?: ${aaresponse.getContentText()}`
  })
  let options = {
    method: "POST",
    contentType: "application/json",
    payload: payload
  };
  UrlFetchApp.fetch(webhookUrl, options);
}
