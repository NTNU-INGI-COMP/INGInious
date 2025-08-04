# -*- coding: utf-8 -*-

import os
import re
import itertools
from random import Random

from flask import send_from_directory
from inginious.common.tasks_problems import Problem
from inginious.frontend.pages.utils import INGIniousPage
from inginious.frontend.task_problems import DisplayableProblem
from inginious.frontend.parsable_text import ParsableText


__version__ = "0.1"

PATH_TO_PLUGIN = os.path.abspath(os.path.dirname(__file__))
PATH_TO_TEMPLATES = os.path.join(PATH_TO_PLUGIN, "templates")


class StaticMockPage(INGIniousPage):
    def GET(self, path):
        return send_from_directory(os.path.join(PATH_TO_PLUGIN, "static"), path)

    def POST(self, path):
        return self.GET(path)

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





class MultifillProblem(Problem):
    """
    A problem where the inputs are placed inline with the text using rst roles.

    The problem allows multiple subtasks, and can use a control string to display random subsets
    """
    def __init__(self, problemid, content, translations, taskfs):
        Problem.__init__(self, problemid, content, translations, taskfs)
        self._header = content.get('header', "")

        if "subtasks" not in content or not isinstance(content['subtasks'], (list, tuple)):
            raise ValueError(f"Multifill problem {problemid} does not have any subtasks")

        self._subtasks = content['subtasks']
        for index, subtask in enumerate(self._subtasks):
            if "text" not in subtask:
                raise ValueError(f"Subtask {index} is missing text")

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

    @classmethod
    def get_type(cls):
        return "multifill"

    @classmethod
    def input_type(cls):
        return dict

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
                giveDetailedFeedback = subtask.get("giveDetailedFeedback", "off").lower()
                subtask["giveDetailedFeedback"] = giveDetailedFeedback in ["on", "true"]

            problem_content["subtasks"] = subtasks

        return problem_content

    @classmethod
    def get_text_fields(cls):
        fields = Problem.get_text_fields()
        fields.update({"header": True, "subtask_string": True, "score_string": True, "subtasks": [{"text": True}]})
        return fields

    def input_is_consistent(self, task_input, default_allowed_extension, default_max_size):
        # Check that the user submission contains everything we expect

        if self.get_id() not in task_input:
            return False
        if not isinstance(task_input[self.get_id()], dict):
            return False

        return True

    def check_answer(self, task_input, language):

        print("================ task_input =================")
        print(task_input)

        return True, None, ["MyCoolMessage"], 0, ""


class DisplayableMultifillProblem(MultifillProblem, DisplayableProblem):
    """
    This is the class responsible for drawing what the studens see
    """

    def __init__(self, problemid, content, translations, taskfs):
        MultifillProblem.__init__(self, problemid, content, translations, taskfs)

    @classmethod
    def get_type_name(self, gettext):
        return "multifill"

    def show_input(self, template_helper, language, seed):
        """ Show MultifillProblem """

        if self._header.strip() != "":
            header = ParsableText(self.gettext(language, self._header), "rst",
                                  translation=self.get_translation_obj(language))
        else:
            header = None

        if self._subtask_string is not None:
            shown_subtask_ids = self._subtask_string.sample_subtasks(self.get_id(), seed)
        else:
            # Include all subtasks
            shown_subtask_ids = list(range(len(self._subtasks)))

        # Rendered html and metadata for the template
        subtasks = []
        for visual_index, subtask_id in enumerate(shown_subtask_ids):
            subtask = { "id": subtask_id }

            if len(shown_subtask_ids) > 1:
                subtask["title"] = chr(ord("a") + visual_index) + ") "

            subtask_text = self._subtasks[subtask_id]["text"]

            INPUT_CHECK = '<input class="ntnu-inline-form-check-input" type="checkbox" name="problem[PID][subtask_string]"></input>'
            INPUT_CHECK = ':raw-html:`' + INPUT_CHECK + "`"
            subtask_text = re.sub(r':input:`[^`]*type=check[^`]*`', INPUT_CHECK, subtask_text)

            INPUT_TEXT = '<input class="ntnu-inline-form-control" type="text" name="problem[PID][subtask_string]"></input>'
            INPUT_TEXT = ':raw-html:`' + INPUT_TEXT + "`"
            subtask_text = re.sub(r':input:`[^`]*`', INPUT_TEXT, subtask_text)

            # Prefix subtask text with definition of raw-html rst role
            subtask_text = (".. role:: raw-html(raw)\n"
                            "   :format: html\n"
                            "\n") + subtask_text

            subtask_html = ParsableText(subtask_text, "rst",
                                  translation=self.get_translation_obj(language))
            subtask["html"] = subtask_html.parse()

            subtasks.append(subtask)

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


def init(plugin_manager, course_factory, client, plugin_config):
    plugin_manager.add_page('/plugins/ntnu_inginious_multifill/static/<path:path>', StaticMockPage.as_view('multifillstaticpage'))
    plugin_manager.add_hook("css", lambda: "/plugins/ntnu_inginious_multifill/static/css/multifill.css")
    plugin_manager.add_hook("javascript_header", lambda: "/plugins/ntnu_inginious_multifill/static/js/multifill.js")
    course_factory.get_task_factory().add_problem_type(DisplayableMultifillProblem)
