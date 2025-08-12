import re
import logging
from random import Random

from inginious.common.tasks_problems import Problem
from inginious.frontend.task_problems import DisplayableProblem
from inginious.frontend.parsable_text import ParsableText

from ntnu_inginious_multifill.common import PATH_TO_TEMPLATES, KeyValueParser

logger = logging.getLogger("inginious.ntnu_inginious_multifill")

def is_valid_id(given_id):
    """ Ensure ids are not empty, and only contain alphanumeric characters, -, _ and + """
    if not given_id:
        return False
    return all(c.isalnum() or c in "-_+" for c in given_id)

class SubtaskString:
    """
    A string like 1;1/2,1 means always display the 1st subtask,
    then pick one of the next two subtasks, and always include the last one.
    The semicolon forces the first task to come first, while commas allow re-ordering.
    """

    def __init__(self, string):
        self.string = string

        # How many subtasks are pulled, and how many are there to pull from
        self.total_pull = 0
        self.total_bag = 0
        self.groups = []

        for loose_group in self.string.split(";"):
            loose_group_result = []
            for group in loose_group.split(","):
                try:
                    if "/" in group:
                        pull, bag = group.split("/")
                    else:
                        pull = group
                        bag = group

                    pull = int(pull)
                    bag = int(bag)
                except ValueError:
                    raise ValueError(f"Subtask string contains illegal group: {self.string}")

                loose_group_result.append((pull, bag))

                self.total_pull += pull
                self.total_bag += bag

                if pull < 0:
                    raise ValueError(f"Subtask string contains negative pull: {self.string}")
                if bag < 1:
                    raise ValueError(f"Subtask string contains empty bag: {self.string}")
                if pull > bag:
                    raise ValueError(f"Subtask string has pull > bag size: {self.string}")

            self.groups.append(loose_group_result)

    @classmethod
    def default_for_subtasks(cls, subtasks):
        """
        Creates a default SubtaskString for a set of subtasks.
        :return: a SubtaskString including each subtask, in order
        """
        synthesized_string = ";".join(["1"] * len(subtasks))
        return cls(synthesized_string)

    def get_total_bag_size(self):
        """
        :return: the number of subtasks to pick from
        """
        return self.total_bag

    def get_total_pull_size(self):
        """
        :return: the number of subtasks that will be included in a pull
        """
        return self.total_pull

    def sample_subtasks(self, task_id, seed):
        """
        Draws a list of subtasks conforming to the Subtask String.
        For a subtask string like 1;2/3, the result can for example be
        [0, 2, 1] or [0, 1, 3]

        :param: task_id the id of the problem
        :param: seed: a string that should be different for each user
        """

        rand = Random(f"{task_id}#{seed}")

        result = []
        bag_counter = 0

        for loose_group in self.groups:
            # Within each loose group, tasks are shuffled
            shuffler = []

            # Extract `pull` out of the next `bag` subtasks
            for pull, bag in loose_group:
                this_bag = list(range(bag_counter, bag_counter + bag))
                bag_counter += bag

                shuffler.extend(rand.sample(this_bag, pull))

            rand.shuffle(shuffler)
            result.extend(shuffler)

        assert bag_counter == self.total_bag

        return result


class ScoreString:
    """
    A string containing three itegers, like 2/3/4
    The first integer is the minimum score required on the task.
    The second integer is the expected score.
    The last is the total score of the problem, evenly distributed among the subtasks.
    While a submission is allowed to perform below expected on a subproblem,
    the total score must be at least equal to the total expected score.
    """

    def __init__(self, string):
        self.string = string

        parts = self.string.split("/")

        if len(parts) != 3:
            raise ValueError(f"Expected 3 parts in score string (min/expected/total), recieved '{self.string}'")

        try:
            self._minimum = int(parts[0])
            self._expected = int(parts[1])
            self._total = int(parts[2])
        except ValueError as e:
            raise ValueError(f"Score string contains illegal score: '{self.string}'")

        if self._minimum < 0 or self._minimum > self._total:
            raise ValueError(f"Minimum score is outside valid range: {self._minimum}")
        if self._expected < 0 or self._expected > self._total:
            raise ValueError(f"Expected score is outside valid range: {self._expected}")
        if self._total < 0:
            raise ValueError(f"Total score can not be negative: {self._total}")

    @classmethod
    def default_for_subtasks(cls, subtasks):
        """
        Creates a default score string for the given set of subtasks.
        :return: a ScoreString: 1 point per subtask. No minimum score, but expecting full marks.
        """
        synthesized_string = f"0/{len(subtasks)}/{len(subtasks)}"
        return cls(synthesized_string)

    def get_minimum(self):
        """
        :return: how many points do you at least need to get on this task,
        in order to pass the exercise
        """
        return self._minimum

    def get_expected(self):
        """
        :return: how many points it is expected to get on this task
        """
        return self._expected

    def get_total(self):
        """
        :return: how many points it is possible to get on this task
        """
        return self._total

    def get_score(self, subtasks_passed, subtasks_shown):
        """
        Returns the score achieved on this task, based on total possible score
        """
        return subtasks_passed * self._total / subtasks_shown


class Input:
    """
    Class representing a single input field in a subtask text.
    Creating inputs in subtasks is done by writing :input:`options`,
    where options is a list of comma separated key and/or key=value pairs.

    A value must be surrounded by "quotes" if it contains commas, spaces or = etc.
    Quotes can be escaped using \" and backslashes using \\

    The full set of options are:
     - id="unique-id-for-this-field"
       Must be globally unique. You only need this if you want to read the input from a run script.

     - type=text (default)
       A textbox that takes arbitrary textual input
     - maxlen=20 (default)
       Sets a maximum length of the textbox. Also affects the size of the input box.
     - answer="answer here"
       The correct answer to the textbox
     - ignorespace
       Allow the input to contain arbitrary spaces that are ignored during checking
     - casesensitive
       Make the comparison case sensitive

     - type=check
       A checkbox
     - answer=true and answer=false
       The options to use when providing the correct answer to a checkbox
    """

    def __init__(self, subtask, index, text):
        """
        :param: subtask: the Subtask this input belongs to
        :param: index: the index of this input
        :param: text: the text content of the input, containing a comma separated list of key=value pairs
        """

        self._subtask = subtask
        self._index = index
        self._text = text

        # Options that will be set when parsing text
        self._id = f"input{self._index}"
        self._html = None
        self._answer = None
        self._type = "text"
        self._maxlen = 20
        self._ignorespace = False
        self._casesensitive = False

        self._parse_text()
        self._validate()

        self._html = self._to_html()

    def get_dict_id(self):
        """
        Gets the dict id of this input, which contains the PID, subtask id, and input id
        """
        return self._subtask.get_dict_id() + f"[{self._id}]"

    def _parse_text(self):
        try:
            options = KeyValueParser(self._text).extract_all()

            keys = [kv[0] for kv in options]
            if len(keys) != len(set(keys)):
                raise ValueError(f"Option string contains duplicate keys")

            for kv in options:
                key = kv[0]
                value = kv[1] if len(kv) >= 2 else None
                if key == "id":
                    if value is None:
                        raise ValueError(f"option 'id' expects a value")
                    self._id = value
                elif key == "type":
                    if value not in ["text", "check"]:
                        raise ValueError(f"option 'type' expects either 'text' or 'check'")
                    self._type = value
                elif key == "maxlen":
                    if value is None:
                        raise ValueError(f"option 'maxlen' expects a value")
                    self._maxlen = int(value)
                elif key == "answer":
                    if value is None:
                        raise ValueError(f"option 'answer' expects a value")
                    self._answer = value
                elif key == "ignorespace":
                    if value is not None:
                        raise ValueError(f"option 'ignorespace' does not take a value")
                    self._ignorespace = True
                elif key == "casesensitive":
                    if value is not None:
                        raise ValueError(f"option 'casesensitive' does not take a value")
                    self._casesensitive = True
                else:
                    raise ValueError(f"Unknown option: {key}" + (f"( = {value})" if value else ""))

        except ValueError as e:
            e.add_note(f"While parsing input {self.get_dict_id()}")
            raise

    def _validate(self):
        try:
            if is_valid_id(self._id):
                raise ValueError(f"Invalid id: {self._id}")
            if self._type == "check" and self._answer not in ["true", "false", None]:
                raise ValueError(f"Input of type check should have answer=true/false. Got: '{self._answer}'")
        except ValueError as e:
            e.add_note(f"in input {self.get_dict_id()}")

    def _to_html(self):
        # We make both text fields and check boxes optional, to allow students to submit partial responses,
        # and to allow multiple choice questions to not have a single correct option.
        # The second part relies on a modification made in inginious/frontend/static/js/task.js

        if self._type == "text":
            classes = ["monospace", "ntnu-inline-form-control"]

            if self._maxlen <= 10:
                classes.append("ntnu-ifc-10char")
            elif self._maxlen <= 20:
                classes.append("ntnu-ifc-20char")
            elif self._maxlen <= 30:
                classes.append("ntnu-ifc-30char")
            elif self._maxlen <= 40:
                classes.append("ntnu-ifc-40char")
            elif self._maxlen <= 50:
                classes.append("ntnu-ifc-50char")
            else:
                classes.append("ntnu-ifc-long")

            return (f'<input type="text" name="{self.get_dict_id()}" '
                    f'class="{ " ".join(classes) }" '
                    f'maxlength="{self._maxlen}" '
                    'autocomplete="off" '
                    'data-optional="True">')
        elif self._type == "check":
            # We wrap the checkbox in a label, since only the label is able to be styled
            return ('<label class="ntnu-inline-form-check-input">'
                    f'<input type="checkbox" name="{self.get_dict_id()}" data-optional="True">'
                    '</label>')


        raise ValueError("Unknown input type")

    def get_html(self):
        return self._html

    def check_answer(self, problem_input):
        """
        :returns: true if the input is correctly answered, false otherwise.
        If no answer is specified, any answer is correct
        """
        if self._answer is None:
            return True

        dict_id = self.get_dict_id()

        if self._type == "text":
            if dict_id not in problem_input:
                return False

            response = problem_input[dict_id]
            if not isinstance(response, str):
                return False

            answer = self._answer

            if self._ignorespace:
                response = response.replace(" ", "").replace("\t", "")
                answer = answer.replace(" ", "").replace("\t", "")

            if not self._casesensitive:
                response = response.lower()
                answer = answer.lower()

            return response == answer

        if self._type == "check":
            # If the checkbox is checked, we get the value "on"
            # If it is not checked we should get no entry in the dict
            # We can also get a list of values if multiple checkboxes share id
            response = problem_input.get(dict_id, "")
            response = len(response) > 0

            answer = self._answer == "true"

            return response == answer

        raise ValueError("Unknown input type")


    @classmethod
    def unqoute_html(cls, text):
        """
        Turn strings like &quot;Hei &lt;3&quot; into "Hei <3"
        """
        return text.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

class Subtask:
    """
    Class representing one subtask in a multifill problem
    """

    input_regex = re.compile(r'<span class="subtask-input">([^<]*)</span>')

    def __init__(self, problem, index, text, detailed_feedback):
        """
        :param: problem: the MultifillProblem this subtask belongs to
        :param: index: the index of the subtask within the problem, 0-indexed.
        :param: text: the text, which should be rst with :input:`` roles.
        :param: detailed_feedback: a bool. If True, feedback is given per input field.
        """
        self._problem = problem
        self._index = index
        self._text = text
        self._detailed_feedback = detailed_feedback

        # Perform a render of the subtask to validate it now, and extract input fields
        self._html, self._inputs = self._render_html()

    def get_dict_id(self):
        return self._problem.get_dict_id() + f"[subtask{self._index}]"

    def get_index(self):
        """ Gets the index of this subtask within the MultifillProblem. 0-indexed. """
        return self._index

    def has_detailed_feedback(self):
        return self._detailed_feedback

    def _render_html(self):
        """
        Renders the body of the subtask, as well as
        :return: a tuple (html, inputs) where html is a string, and inputs is a list of Inputs
        """

        # Prefix subtask text with definition of rst input role
        subtask_text = (".. role:: input\n"
                        "   :class: subtask-input\n"
                        "\n") + self._text

        subtask_html = ParsableText(subtask_text, "rst").parse()

        # Replace all input spans with proper Input objects rendered as html
        inputs = []
        html_parts = []
        last_end = 0
        for m in Subtask.input_regex.finditer(subtask_html):
            html_parts.append(subtask_html[last_end : m.start()])

            input_text = Input.unqoute_html(m.group(1))
            input_object = Input(self, len(inputs), input_text)

            inputs.append(input_object)
            html_parts.append(input_object.get_html())
            last_end = m.end()

        # add the final rest of subtask_html
        html_parts.append(subtask_html[last_end:])

        return "".join(html_parts), inputs

    def get_visual_index_input_name(self):
        """
        When a subtask is rendered for a user, it includes a hidden input with its visual index.
        """
        return f"{self.get_dict_id()}[visual_index]"

    def get_html(self, visual_index):
        """
        Retrieves html for this subtask.
        :param: visual_index, the index of this subtask in the list of subtasks that are actually rendered for a given user. 0-indexed
        """
        visual_index_input = f'<input type="hidden" name="{self.get_visual_index_input_name()}" value="{visual_index}">'
        return self._html + "\n" + visual_index_input

    def check_answer(self, problem_input):
        """
        Checks all inputs in this subtask against the given dict of problem inputs
        :return: a tuple (passed_inputs, failed_inputs), the inputs that passed or failed
        """
        passed_inputs = []
        failed_inputs = []

        for inp in self._inputs:
            if inp.check_answer(problem_input):
                passed_inputs.append(inp)
            else:
                failed_inputs.append(inp)

        return passed_inputs, failed_inputs


class MultifillProblem(Problem):
    """
    A problem where the inputs are placed inline with the text using rst roles.

    The problem allows multiple subtasks, and can use a control string to display random subsets
    """
    def __init__(self, problemid, content, translations, taskfs):
        Problem.__init__(self, problemid, content, translations, taskfs)

        if not is_valid_id(problemid):
            raise ValueError(f"Multifill problem has an invalid problem id: '{problemid}'")

        self._header = content.get('header', "")

        if "subtasks" not in content or not isinstance(content['subtasks'], (list, tuple)):
            raise ValueError(f"Multifill problem {problemid} does not have any subtasks")

        # Create subtask objects, also checks that rendering works
        self._subtasks = []
        for index, subtask in enumerate(content['subtasks']):
            self._subtasks.append(Subtask(self,
                                          index,
                                          subtask.get("text", ""),
                                          subtask.get("giveDetailedFeedback", False)))

        # The subtask string describes which subtasks to display.
        # The default is to display all subtasks
        # If there is only one displayed subtask, the subtask letter (a) is omitted
        if content.get("subtask_string", "").strip() != "":
            self._subtask_string = SubtaskString(content["subtask_string"])
        else:
            self._subtask_string = SubtaskString.default_for_subtasks(self._subtasks)

        # Check that the subtask string adds up to the correct amount of subtasks
        num_subtasks = len(self._subtasks)
        total_bag = self._subtask_string.get_total_bag_size()
        if num_subtasks != total_bag:
            raise ValueError(f"Problem {problemid} has {num_subtasks} subtasks, but the subtask string expects {total_bag}.")

        # The score string decides how many points one gets from the task,
        # and how many points are needed to not fail the exercise.
        # It also contains expected score, which must be satisfied on average across all tasks
        if content.get("score_string", "").strip() != "":
            self._score_string = ScoreString(content["score_string"])
        else:
            self._score_string = ScoreString.default_for_subtasks(self._subtasks)

    def get_dict_id(self):
        """
        All input form fields associated with this problem should have names on the form
          my-problem[subtask2][rs1]
        The dict input type then gives us all fields that start with "my-problem["
        """
        return self.get_id()

    @classmethod
    def get_type(cls):
        return "multifill"

    @classmethod
    def input_type(cls):
        return "dict"

    @classmethod
    def parse_problem(cls, problem_content):
        """
        Takes the data returned from the studio and converts it into the storage format
        """
        problem_content = Problem.parse_problem(problem_content)

        # Turn subtasks into a list, instead of a dict
        if "subtasks" in problem_content:
            # Use the dict key to sort the subtasks
            subtasks = [(int(key), value) for key, value in problem_content["subtasks"].items()]
            subtasks.sort()
            # Once the subtasks have been sorted by key, stip away the key
            subtasks = [val for _, val in subtasks]

            # Each subtask is a dict which should contain
            #  - text
            #  - giveDetailedFeedback (bool) if true, feedback is given per text field
            for subtask in subtasks:
                assert isinstance(subtask, dict)

                if "text" not in subtask:
                    subtask["text"] = ""

                # Convert giveDetailedFeedback to a boolean
                detailed_feedback = subtask.get("giveDetailedFeedback", "off").lower()
                subtask["giveDetailedFeedback"] = detailed_feedback in ["on", "true"]

            problem_content["subtasks"] = subtasks

        return problem_content

    @classmethod
    def get_text_fields(cls):
        fields = Problem.get_text_fields()
        fields.update({"header": True, "subtask_string": True, "score_string": True, "subtasks": [{"text": True}]})
        return fields

    def input_is_consistent(self, task_input, default_allowed_extension, default_max_size):
        """
        Check that the user submission contains everything we expect,
        before sending the response to the evaluation agent.
        """

        if self.get_id() not in task_input:
            return False
        if not isinstance(task_input[self.get_id()], dict):
            return False

        return True

    def check_answer(self, task_input, language):
        """
        Called by agents that are not the MultifillAgent.
        In which case we always ask to be checked by a runfile in a docker container.
        """
        return  None, None, None, 0, ""

    def check_multifill_answers(self, task_input, language):
        """
        Called by the MultifillAgent to evaluate the submission.
        Returns a tuple containing:
         - The score string
         - A list of passed subtasks
         - A list of failed subtasks
         - A list passed inputs, for failed subtasks with detailed feedback
         - A list failed inputs, for failed subtasks with detailed feedback
        """
        # Sample subtasks using the user's username, to ensure people are not cheating by submitting other subtasks
        username = task_input['@username']
        shown_subtask_idxs = self._subtask_string.sample_subtasks(self.get_id(), username)
        shown_subtasks = [self._subtasks[idx] for idx in shown_subtask_idxs]

        problem_input = task_input[self.get_id()]

        subtasks_passed = []
        subtasks_failed = []
        # Only if a subtask has detailed feedback are individual inputs corrected
        subtask_inputs_passed = []
        subtask_inputs_failed = []
        for subtask in shown_subtasks:
            passed_inputs, failed_inputs = subtask.check_answer(problem_input)

            if len(failed_inputs) == 0:
                # Passed the subtask!
                subtasks_passed.append(subtask)
            else:
                subtasks_failed.append(subtask)
                # Possibly give even more details
                if subtask.has_detailed_feedback():
                    subtask_inputs_passed.extend(passed_inputs)
                    subtask_inputs_failed.extend(failed_inputs)

        assert len(subtasks_passed) + len(subtasks_failed) == len(shown_subtasks)

        return (self._score_string,
                subtasks_passed,
                subtasks_failed,
                subtask_inputs_failed,
                subtask_inputs_passed)


class DisplayableMultifillProblem(MultifillProblem, DisplayableProblem):
    """
    This is the class responsible for drawing what the studens see,
    and what the admin sees in the problem "studio".
    """

    def __init__(self, problemid, content, translations, taskfs):
        MultifillProblem.__init__(self, problemid, content, translations, taskfs)

    @classmethod
    def get_type_name(self, gettext):
        return "multifill"

    def show_input(self, template_helper, language, seed):
        """ Render the MultifillProblem for displaying to a student """

        if self._header.strip() != "":
            header = ParsableText(self.gettext(language, self._header), "rst",
                                  translation=self.get_translation_obj(language))
        else:
            header = None

        # The seed is actually the username of the student
        shown_subtask_idxs = self._subtask_string.sample_subtasks(self.get_id(), seed)
        shown_subtasks = [self._subtasks[idx] for idx in shown_subtask_idxs]

        # Rendered html and metadata for the template
        subtasks = []
        for visual_index, subtask in enumerate(shown_subtasks):
            subtask_data = {
                "dict_id": subtask.get_dict_id(),
                "has_detailed_feedback": subtask.has_detailed_feedback()
            }

            if len(shown_subtasks) > 1:
                subtask_data["title"] = chr(ord("a") + visual_index) + ") "
            subtask_data["html"] = subtask.get_html(visual_index)

            subtasks.append(subtask_data)

        return template_helper.render("tasks/multifill.html",
                                      template_folder=PATH_TO_TEMPLATES, inputId=self.get_id(),
                                      header=header, subtasks=subtasks)

    @classmethod
    def show_editbox(cls, template_helper, key, language):
        """
        This is the top level task editor interface.
        The rendered template does not contain any problem-sepecific content.
        """
        return template_helper.render("tasks/multifill_editbox.html",
                                      template_folder=PATH_TO_TEMPLATES, key=key)

    @classmethod
    def show_editbox_templates(cls, template_helper, key, language):
        """
        This is the template of the per subtask editor.
        It is rendered once on the server, and copied in the browser using js.
        """
        return template_helper.render("tasks/multifill_editbox_templates.html",
                                      template_folder=PATH_TO_TEMPLATES, key=key)
