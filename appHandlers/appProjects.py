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
    # New, rename, close
    # ------------------------------------------------------------------------------------------------------------
    def new(self, visuals=True):
        """
        Add an empty project and make it active.

        :return:    the new ProjectContext, or None if a task runs
        """
        if self.is_busy():
            self.inform_busy()
            return None

        ctx = self.add_context(self.default_name())
        if not self.switch(ctx, visuals=visuals):
            self._dispose(ctx)
            return None
        return ctx

    def rename(self, ctx, name):
        """
        :return:    True if the name changed. False if the name is not valid or another project uses it.
        """
        name = name.strip() if name else ''
        if not is_valid_name(name):
            return False
        if name in [other.name for other in self.contexts if other is not ctx]:
            return False

        ctx.name = name
        self.projects_changed.emit()
        if ctx is self.active:
            self.update_title()
        return True

    def is_dirty(self, ctx):
        """
        True if the project has unsaved changes. A project with a file is dirty when its flag is set, also when it
        is empty: the deletion of all its objects is a change. A project without a file and without objects has
        nothing to save, the same rule as the exit of the app with 1 project (AppLifecycle.final_save).
        """
        flag = self.app.should_we_save if ctx is self.active else ctx.should_we_save
        if not flag:
            return False
        return bool(ctx.collection.get_list()) or self.filename_of(ctx) is not None

    def dirty_contexts(self):
        return [ctx for ctx in self.contexts if self.is_dirty(ctx)]

    def close(self, ctx, force=False, visuals=True):
        """
        Close and remove a project. There is no dialog.

        :param ctx:     the project to close
        :param force:   if True, a project with unsaved changes is closed and the changes are lost
        :param visuals: passed to switch()
        :return:        True if the project is removed
        """
        if ctx not in self.contexts:
            return False
        if self.is_dirty(ctx) and not force:
            return False
        if self.is_busy():
            self.inform_busy()
            return False

        if ctx is self.active:
            if len(self.contexts) > 1:
                idx = self.contexts.index(ctx)
                target = self.contexts[idx - 1] if idx > 0 else self.contexts[idx + 1]
                if not self.switch(target, visuals=visuals):
                    return False
            elif self.new(visuals=visuals) is None:
                return False

        self._dispose(ctx)
        return True

    def _dispose(self, ctx):
        """
        Remove an inactive project from the list and release its objects.
        """
        if ctx in self.contexts:
            self.contexts.remove(ctx)
        if self.displayed is ctx:
            self.displayed = None

        for obj in ctx.collection.get_list():
            try:
                obj.clear(update=False)
            except Exception as err:
                self.app.log.error("ProjectManager._dispose() --> %s" % str(err))
            try:
                obj.mark_shapes.clear(update=False)
                obj.mark_shapes.parent = None
            except AttributeError:
                pass

        self.stack.removeWidget(ctx.collection.view)
        ctx.collection.view.deleteLater()
        try:
            ctx.collection.deleteLater()
        except AttributeError:
            pass
        ctx.collection = None
        self.projects_changed.emit()

    # ------------------------------------------------------------------------------------------------------------
    # File name rules
    # ------------------------------------------------------------------------------------------------------------
    def save_target(self, ctx=None):
        """
        The file that a Save of the project writes.

        :return:    None if the project has no file (then Save As is needed). The current file if the project name
                    is the file name. Else, '<name>.FlatPrj' in the folder of the current file.
        """
        ctx = ctx if ctx is not None else self.active
        filename = self.filename_of(ctx)
        if not filename:
            return None
        if name_from_filename(filename) == ctx.name:
            return filename
        return os.path.join(os.path.dirname(filename), ctx.name + PROJECT_EXT)

    def adopt_filename(self, filename):
        """
        The active project now uses this file: its name becomes the file name.
        Called after an open and after a Save As.
        """
        ctx = self.active
        ctx.filename = filename
        used = [other.name for other in self.contexts if other is not ctx]
        ctx.name = unique_name(name_from_filename(filename), used)
        self.projects_changed.emit()
        self.update_title()

    # ------------------------------------------------------------------------------------------------------------
    # Steps that change the GUI
    # ------------------------------------------------------------------------------------------------------------
    # these object kinds have no shapes on the canvas
    NO_SHAPES_KINDS = ('script', 'document')

    def reset_options(self):
        """
        A new project copies the project keys from the application defaults. The application settings are the
        same for all projects, so they do not change.
        """
        self.app.on_defaults2options()

    def before_switch(self):
        """
        Remove the canvas helpers of the current project. A switch never runs while an editor is open (is_busy),
        so this method does not close an editor.
        """
        app = self.app
        for attr in ('tool_shapes', 'hover_shapes'):
            shapes = getattr(app, attr, None)
            if shapes is not None:
                try:
                    shapes.clear(update=True)
                except Exception as err:
                    app.log.error("ProjectManager.before_switch() %s --> %s" % (attr, str(err)))

        try:
            app.levelling_tool.probing_shapes.clear(update=True)
        except AttributeError:
            pass

        if getattr(app, 'exc_areas', None) is not None:
            app.exc_areas.clear_shapes()

        app.delete_selection_shape()

    def deactivate(self, ctx):
        """
        Release the plot shapes of the objects of a project. The geometry and the Properties UI stay.
        """
        # the Properties tab can show the UI of an object of this project; replace it first
        self.app.setup_default_properties_tab()

        for obj in ctx.collection.get_list():
            if obj.kind in self.NO_SHAPES_KINDS:
                continue
            try:
                obj.clear(update=False)
            except Exception as err:
                self.app.log.error("ProjectManager.deactivate() --> %s" % str(err))
            try:
                obj.mark_shapes.clear(update=False)
            except AttributeError:
                pass
            # forces a full plot when the project is active again
            obj._full_plot_sig = None

        self.app.plotcanvas.redraw()

    def activate(self, ctx):
        """
        Re-create the plugins for the new collection and plot. The Properties UI of the objects is not built again:
        set_ui() changes the data of a CNCJob and connects the object signals again.
        """
        app = self.app
        app.setup_default_properties_tab()

        # show the project keys of this project in the Preferences form
        app.preferencesUiManager.defaults_write_form()

        # the plugin comboboxes hold the model of the old collection; File -> New Project also does this
        app.init_tools(init_tcl=False)

        if ctx.collection.get_list():
            app.plot_all(fit_view=False)
        self._set_view_rect(ctx.view_rect)

    def _get_view_rect(self):
        try:
            from vispy.geometry import Rect
            return Rect(self.app.plotcanvas.view.camera.rect)
        except Exception:
            return None

    def _set_view_rect(self, rect):
        if rect is None:
            return
        try:
            self.app.plotcanvas.view.camera.rect = rect
        except Exception as err:
            self.app.log.error("ProjectManager._set_view_rect() --> %s" % str(err))
