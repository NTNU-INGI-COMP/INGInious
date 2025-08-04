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

function load_input_multifill(submissionid, key, input)
{
  /*
    if(key in input) {
        codeEditors[key].toTextArea();
        var elem = $('textarea[name="'+key+'"]')
        if (typeof input[key] === 'object'
            && 'input' in input[key]
            && 'template' in input[key]
            && input[key].template == elem.attr('data-x-template')
        ) {
            elem[0].value = input[key].input;
        } else {
            elem[0].value = elem.attr('data-x-template')
        }
        registerCodeEditor(elem[0], elem.attr('data-x-language'), elem.attr('data-x-lines'));
    } else {
        // TODO: console.log("No idea what to do here")
    }
    */
}
