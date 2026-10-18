from copy import deepcopy
import os

from PyQt6 import QtCore, QtWidgets

from appObjects.ProjectContext import ProjectContext, unique_name, same_path, name_from_filename, \
    is_valid_name, PROJECT_EXT
from defaults import project_options

# App Translation
import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class ProjectManager(QtCore.QObject):
    """
    Holds the projects of the Project tab. Only 1 project is active. The state of the active project is in the
    App attributes, so the existing code that reads app.collection works on the active project.
    """

    # emitted when the list of projects, a name or the active project changes
    projects_changed = QtCore.pyqtSignal()

    def __init__(self, app, collection_factory=None):
        super().__init__()
        self.app = app
        self.collection_factory = collection_factory if collection_factory is not None else self._make_collection

        # 1 tree view for each project; a switch shows the view of the active project
        self.stack = QtWidgets.QStackedWidget()

        first = ProjectContext(name=self.default_name(), collection=app.collection)
        self.contexts = [first]
        self.active = first
        # the project that the canvas shows. It is not always the active project: a switch with visuals=False
        # (used on exit) changes the active project but not the canvas.
        self.displayed = first
        self.stack.addWidget(first.collection.view)
        self.stack.setCurrentWidget(first.collection.view)

    def _make_collection(self):
        from appObjects.ObjectCollection import ObjectCollection

        collection = ObjectCollection(app=self.app)
        collection.view.setMinimumWidth(290)
        return collection

    # ------------------------------------------------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------------------------------------------------
    def names(self):
        return [ctx.name for ctx in self.contexts]

    def default_name(self):
        used = [ctx.name for ctx in getattr(self, 'contexts', [])]
        return unique_name('%s_1' % _("Project"), used)

    def get_by_name(self, name):
        for ctx in self.contexts:
            if ctx.name == name:
                return ctx
        return None

    def filename_of(self, ctx):
        # the live filename of the active project is in the App
        return self.app.project_filename if ctx is self.active else ctx.filename

    def find_by_filename(self, filename):
        for ctx in self.contexts:
            if same_path(self.filename_of(ctx), filename):
                return ctx
        return None

    def is_editing(self):
        """
        True if an editor is open. A switch then would lose the changes of the editor.
        """
        return getattr(self.app, 'call_source', 'app') != 'app'

    def is_busy(self):
        """
        True if a switch is not allowed now: an editor is open, or a task is queued or runs. A task that ends after
        a switch can add its result to the wrong project.
        """
        app = self.app
        if self.is_editing():
            return True
        # a task counts from the moment it is queued, before its worker starts. A worker that hands its result to
        # the GUI thread (for example the parse of a project, which then starts the restore of the objects) posts
        # that signal before its "task completed" signal, so the next stage is registered before this count is 0.
        workers = getattr(app, 'workers', None)
        if workers is not None and workers.pending_count() > 0:
            return True
        try:
            if app.proc_container.get_procs_count() > 0:
                return True
        except AttributeError:
            pass
        if getattr(app, 'save_in_progress', False) or getattr(app, 'project_save_pending', False):
            return True
        collection = app.collection
        if collection.has_promises() or collection.has_plot_promises():
            return True
        return bool(getattr(getattr(app, 'app_obj', None), 'load_batches', None))

    def inform_busy(self):
        if self.is_editing():
            msg = _("Close the editor first.")
        else:
            msg = _("A task is running. Wait until it ends.")
        self.app.inform.emit('[WARNING_NOTCL] %s' % msg)

    # ------------------------------------------------------------------------------------------------------------
    # Switch
    # ------------------------------------------------------------------------------------------------------------
    def add_context(self, name):
        """
        Add an empty project to the list. It does not become active.
        """
        ctx = ProjectContext(name=unique_name(name, self.names()), collection=self.collection_factory())
        self.contexts.append(ctx)
        self.stack.addWidget(ctx.collection.view)
        self.projects_changed.emit()
        return ctx

    def capture(self):
        """
        Write the live state of the active project from the App back into its context.
        """
        ctx = self.active
        # only the project keys; the application settings stay in app.defaults for all projects
        ctx.options = deepcopy(project_options(self.app.options))
        ctx.filename = self.app.project_filename
        ctx.should_we_save = self.app.should_we_save
        # the canvas shows the view of the displayed project; after a switch with visuals=False that is another
        # project, and its view must not go into this context
        if ctx is self.displayed:
            ctx.view_rect = self._get_view_rect()

    def _load(self, ctx):
        """
        Put the state of the context into the App.
        """
        self.app.collection = ctx.collection
        if ctx.options is not None:
            # copies the project keys from the defaults, then puts the saved project keys over them
            self.app.options.load_project(deepcopy(ctx.options))
        else:
            self.reset_options()
        self.app.project_filename = ctx.filename
        self.app.should_we_save = ctx.should_we_save
        self.app.all_objects_list = ctx.collection.get_list()
        self.stack.setCurrentWidget(ctx.collection.view)

    def switch(self, ctx, visuals=True):
        """
        Make ctx the active project.

        :param ctx:     the ProjectContext to activate
        :param visuals: if False, the plots and the plugins are not changed (used on exit)
        :return:        True if ctx is now the active project
        """
        if ctx is self.active:
            return True
        if ctx not in self.contexts:
            return False
        if self.is_busy():
            self.inform_busy()
            return False

        self.capture()
        if visuals:
            self.before_switch()
            # release the project that the canvas shows; after a switch with visuals=False it is not the active one
            if self.displayed is not None:
                self.deactivate(self.displayed)

        self.active = ctx
        self._load(ctx)

        if visuals:
            self.activate(ctx)
            self.displayed = ctx

        self.projects_changed.emit()
        self.update_title()
        return True

    def update_title(self):
        self.app.ui.set_ui_title(name=self.active.name)

    # ------------------------------------------------------------------------------------------------------------
    # Steps that change the GUI. Task 5 fills them.
    # ------------------------------------------------------------------------------------------------------------
    def reset_options(self):
        pass

    def before_switch(self):
        pass

    def deactivate(self, ctx):
        pass

    def activate(self, ctx):
        pass

    def _get_view_rect(self):
        return None
