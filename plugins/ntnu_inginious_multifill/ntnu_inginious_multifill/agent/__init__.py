# -*- coding: utf-8 -*-
#
# This file is based on the inginious/agent/mcq_agent/__init__.py from INGIninious
import json
import logging
import gettext

from inginious.agent import Agent, CannotCreateJobException
from inginious.common.messages import BackendNewJob, BackendKillJob
import os.path
import builtins

from ntnu_inginious_multifill.problem import MultifillProblem
from ntnu_inginious_multifill.common import PATH_TO_AGENT_I18N

class MultifillAgent(Agent):
    def __init__(self, context, backend_addr, friendly_name, concurrency, tasks_filesystem):
        """
        :param context: ZeroMQ context for this process
        :param backend_addr: address of the backend (for example, "tcp://127.0.0.1:2222")
        :param friendly_name: a string containing a friendly name to identify agent
        :param tasks_filesystem: FileSystemProvider to the course/tasks
        """
        super().__init__(context, backend_addr, friendly_name, concurrency, tasks_filesystem)
        self._logger = logging.getLogger("inginious.ntnu_inginious_multifill.agent")

        # Init gettext
        self._translations = {"en": gettext.NullTranslations()}
        available_translations = [x for x in os.listdir(PATH_TO_AGENT_I18N) if os.path.isdir(os.path.join(PATH_TO_AGENT_I18N, x))]
        self._translations.update({
            lang: gettext.translation('messages', PATH_TO_AGENT_I18N, [lang]) for lang in available_translations
        })

    @property
    def environments(self):
        return {"multifill": {"multifill": {"id": "multifill", "created": 0}}}

    async def new_job(self, msg: BackendNewJob):
        language = msg.inputdata.get("@lang", "")
        previous_state = msg.inputdata.get("@state", "")
        translation = self._translations.get(language, gettext.NullTranslations())
        # TODO: this would probably require a refactor.
        # This may pose problem with apps that start multiple MultifillAgents in the same process...
        builtins.__dict__['_'] = translation.gettext

        course_fs = self._fs.from_subfolder(msg.course_id)
        task_fs = course_fs.from_subfolder(msg.task_id)
        translations_fs = task_fs.from_subfolder("$i18n")
        if not translations_fs.exists():
            translations_fs = task_fs.from_subfolder("student").from_subfolder("$i18n")
        if not translations_fs.exists():
            translations_fs = course_fs.from_subfolder("$common").from_subfolder("$i18n")
        if not translations_fs.exists():
            translations_fs = course_fs.from_subfolder("$common").from_subfolder("student")\
                .from_subfolder("$i18n")

        if translations_fs.exists() and translations_fs.exists(language + ".mo"):
            translations = {language: gettext.GNUTranslations(translations_fs.get_fd(language + ".mo"))}
        else:
            translations = {language: gettext.NullTranslations()}

        # Create MultifillProblem instances for each subproblem
        problems = []
        for problemid, problem_content in msg.task_problems.items():
            problem_type = problem_content.get("type", None)
            if problem_type == MultifillProblem.get_type():
                problems.append(MultifillProblem(problemid, problem_content, translations, task_fs))
            else:
                self._logger.warning(f"Multifill grader can not evaluate subproblems of type '{problem_type}'")

        # If there are no Multifill problems, quit now
        if len(problems) == 0:
            grade = 0.0
            await self.send_job_result(msg.job_id, "crashed", "No multifill problems", grade, {}, {}, {}, previous_state, None)
            return

        result, grade, main_message, problem_messages = self._check_answers(problems, msg.inputdata, language)

        await self.send_job_result(job_id=msg.job_id,
                                   result="success" if result else "failed",
                                   text="\n\n".join(main_message),
                                   grade=grade,
                                   problems=problem_messages,
                                   tests=None, # Tests are only visible to admins. Can not be used to provide user feedback
                                   custom=None, # Custom data is not passed to the client either :(
                                   state=previous_state)

    def _check_answers(self, problems, task_input, language):
        """ Verify the answers in task_input. Returns six values:

        :returns: a tuple containing the following
         - result: true if the task was passed
         - grade: a number between 0.0 and 100.0, the ratio of total score achieved
         - main_message: a list of lines containing info about the grading, already translated
         - problem_messages: a dictionary where keys are problem ids, and values are (problem result, problem message in rst)
        """

        result = True
        main_message = []
        problem_messages = {}

        total_points_achieved = 0.0
        total_points_expected = 0.0
        total_points_possible = 0.0

        rounding = 1 # Round all scores to this number of decimals
        epsilon = .05 # To avoid floating point rounding errors failing students

        for problem in problems:
            score_string, subtasks_passed, subtasks_failed, subtask_inputs_failed, subtask_inputs_passed, subtask_messages = problem.check_multifill_answers(task_input, language)

            problem_result = "success"
            problem_message = []

            achieved = score_string.get_score(len(subtasks_passed), len(subtasks_passed) + len(subtasks_failed))
            achieved = round(achieved, rounding)
            minimum = score_string.get_minimum()
            possible = score_string.get_total()

            total_points_achieved += achieved
            total_points_expected += score_string.get_expected()
            total_points_possible += possible

            problem_message.append(_("Points on this problem: {:g} / {:g}").format(achieved, possible))

            if achieved + epsilon < score_string.get_minimum():
                result = False
                problem_result = "failed"
                problem_message.append(_("You need at least {:g} points on this problem").format(minimum))

            problem_message.extend(subtask_messages)

            # Provide feedback per subtask, or even per input when detailed feedback is configure
            success = []
            failed = []
            for subtask in subtasks_passed:
                success.append(subtask.get_dict_id())
            for subtask in subtasks_failed:
                failed.append(subtask.get_dict_id())
            for inp in subtask_inputs_passed:
                success.append(inp.get_dict_id())
            for inp in subtask_inputs_failed:
                failed.append(inp.get_dict_id())

            # Use rst to hide extra data in the problem response
            details = (".. role:: success\n"
                       "   :class: multifill-subtasks-success\n"
                       "\n"
                       ".. role:: failed\n"
                       "   :class: multifill-subtasks-failed\n"
                       "\n")
            if success:
                details += f":success:`{','.join(success)}`\n"
            if failed:
                details += f":failed:`{','.join(failed)}`\n"

            problem_messages[problem.get_id()] = (problem_result, details + "\n\n".join(problem_message))

        main_message.append(_("Total points on this exercise: {:g} / {:g}").format(total_points_achieved, total_points_possible))

        if total_points_achieved + epsilon < total_points_expected:
            main_message.append(_("You need at least {:g} points to pass the exercise").format(total_points_expected))
            result = False

        grade = total_points_achieved * 100 / total_points_possible

        return result, grade, main_message, problem_messages

    async def kill_job(self, message: BackendKillJob):
        pass
