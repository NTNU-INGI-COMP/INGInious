"use strict";

/**
 * Init the editbox for a multifill problem
 * @param well: the DOM element containing the input fields
 * @param pid
 * @param problem
 */
function studio_init_template_multifill(well, pid, problem)
{
  // The studio automatically fills in the subproblem title and header textbox
  const subtask_string = $("#" + pid + "--subtask_string", well)[0];
  if ("subtask_string" in problem)
    subtask_string.value = problem["subtask_string"];

  const score_string = $("#" + pid + "--score_string", well)[0];
  if ("score_string" in problem)
    score_string.value = problem["score_string"];

  jQuery.each(problem["subtasks"], function(index, elem)
  {
    studio_create_multifill_subtask(pid, elem);
  });
}

/**
 * Create the edit box for a subtask in a given multifill problem.
 * This method is used both when creating existing subtasks, and new ones
 * @param pid
 * @param subtask_data data about the subtask, empty object if new
 */
function studio_create_multifill_subtask(pid, subtask_data) {
  // The studio provides a div for us to work inside, called the well
  const well = $(studio_get_problem(pid));
  const subtask_list = $("#" + pid + "--multifill-subtasks", well);

  var subtask_id = 0;

  if ("id" in subtask_data)
    subtask_id = subtask_data["id"];
  else {
    // Subtasks are always created and deleted from the end
    subtask_id = subtask_list.children().length;
  }

  const row = $("#template_subproblem_multifill_subtask").html();
  const new_row_content = row.replace(/PID/g, pid)
                           .replace(/SUBTASK_ONE_INDEXED/g, subtask_id+1)
                           .replace(/SUBTASK/g, subtask_id);
  const new_row = $("<div></div>").html(new_row_content);
  subtask_list.append(new_row);

  const editor = registerCodeEditor($(".subproblem_multifill_subtask_text", new_row)[0], 'rst', 1);
  if ("text" in subtask_data)
    editor.setValue(subtask_data["text"]);

  const detailedFeedbackCheckbox = $(".subproblem_multifill_subtask_giveDetailedFeedback", new_row)[0];
  if ("giveDetailedFeedback" in subtask_data)
    detailedFeedbackCheckbox.checked = subtask_data["giveDetailedFeedback"];
}

/**
 * Removes the last multifill subtask, or no-op if it has none
 */
function studio_delete_multifill_last_subtask(pid) {
  // The studio provides a div for us to work inside, called the well
  const well = $(studio_get_problem(pid));
  const subtask_list = $("#" + pid + "--multifill-subtasks", well);

  subtask_list.children().last().remove();
}

function load_input_multifill(submissionid, pid, input) {
  const subtasks_div = $("#" + pid + "--multifill-subtasks");

  const task_input = input[pid];
  if (!(task_input instanceof Object))
    return;

  // Go through all visible inputs within the subtask and fill them in
  for (const input_elm of subtasks_div.find('input')) {
    const type = $(input_elm).attr('type');
    const name = $(input_elm).attr('name');
    if (type === "text") {
      $(input_elm).val(task_input[name] ?? "");
    } else if (type === "checkbox") {
      $(input_elm).prop('checked', (task_input[name] ?? "").length > 0);
    }
  }
}

const MULTIFILL_SUCCESS_CLASS = "multifill-success";
const MULTIFILL_FAILED_CLASS = "multifill-failed";
const SUBTASK_SHOW_DETAILED_CLASS = "multifill-show-detailed-feedback";

function load_feedback_multifill(pid, content) {
  const subtasks_div = $("#" + pid + "--multifill-subtasks")
  // Start by removing all previous success and failure markers
  // and disabling showing detailed feedback
  subtasks_div.find('*').removeClass([MULTIFILL_SUCCESS_CLASS, MULTIFILL_FAILED_CLASS, SUBTASK_SHOW_DETAILED_CLASS]);

  const response_body = content[1];

  const success_match = response_body.match(/<span class="multifill-subtasks-success">([^<]*)<\/span>/);
  const failed_match = response_body.match(/<span class="multifill-subtasks-failed">([^<]*)<\/span>/);

  var success_ids = [];
  var failed_ids = [];

  if (success_match !== null)
    success_ids = success_match[1].split(",");
  if (failed_match !== null)
    failed_ids = failed_match[1].split(",");

  var alert_type = "danger";
  if (content[0] === "timeout" || content[0] === "overflow")
    alert_type = "warning";
  else if(content[0] === "success") {
    // If we have some failed subtasks / inputs, we do not want to be fully green
    if (failed_ids.length === 0)
      alert_type = "success"
    else
      alert_type = "warning";
  }

  $("#task_alert_" + pid).html(getAlertCode("", response_body, alert_type, false));

  for (const success_id of success_ids) {
    $(`[name="${success_id}"]`, subtasks_div).addClass(MULTIFILL_SUCCESS_CLASS);
  }
  for (const failed_id of failed_ids) {
    $(`[name="${failed_id}"]`, subtasks_div).addClass(MULTIFILL_FAILED_CLASS);
  }
}

function show_detailed_feedback_multifill(subtask_id) {
  const subtask_div = $(`[name="${subtask_id}"]`);
  subtask_div.addClass(SUBTASK_SHOW_DETAILED_CLASS);
  return false;
}

function hide_detailed_feedback_multifill(subtask_id) {
  const subtask_div = $(`[name="${subtask_id}"]`);
  subtask_div.removeClass(SUBTASK_SHOW_DETAILED_CLASS);
  return false;
}
