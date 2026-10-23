# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 09/27/2019                                         #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets, QtCore, QtGui
from appGUI.GUIElements import FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox, \
    FCDoubleSpinner, OptionalInputSection

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


def render_report(res, decimals):
    txt = ''
    for el in res:
        txt += '<b>RULE NAME:</b>&nbsp;&nbsp;&nbsp;&nbsp;%s<BR>' % str(el[0]).upper()
        if isinstance(el[1][0]['name'], list):
            for name in el[1][0]['name']:
                txt += 'File name: %s<BR>' % str(name)
        else:
            txt += 'File name: %s<BR>' % str(el[1][0]['name'])

        point_txt = ''
        try:
            if el[1][0]['points']:
                txt += '{title}: <span style="color:{color};background-color:{h_color}"' \
                       '>&nbsp;{status} </span>.<BR>'.format(title=_("STATUS"),
                                                             h_color='red',
                                                             color='white',
                                                             status=_("FAILED"))
                if 'Failed' in el[1][0]['points'][0]:
                    point_txt = el[1][0]['points'][0]
                else:
                    for pt in el[1][0]['points']:
                        point_txt += '(%.*f, %.*f)' % (decimals, float(pt[0]), decimals, float(pt[1]))
                        point_txt += ', '
                txt += 'Violations: %s<BR>' % str(point_txt)
            else:
                txt += '{title}: <span style="color:{color};background-color:{h_color}"' \
                       '>&nbsp;{status} </span>.<BR>'.format(title=_("STATUS"),
                                                             h_color='green',
                                                             color='white',
                                                             status=_("PASSED"))
                txt += '%s<BR>' % _("Violations: There are no violations for the current rule.")
        except KeyError:
            pass

        try:
            if el[1][0]['dia']:
                txt += '{title}: <span style="color:{color};background-color:{h_color}"' \
                       '>&nbsp;{status} </span>.<BR>'.format(title=_("STATUS"),
                                                             h_color='red',
                                                             color='white',
                                                             status=_("FAILED"))
                if 'Failed' in el[1][0]['dia']:
                    point_txt = el[1][0]['dia']
                else:
                    for pt in el[1][0]['dia']:
                        point_txt += '%.*f' % (decimals, float(pt))
                        point_txt += ', '
                txt += 'Violations: %s<BR>' % str(point_txt)
            else:
                txt += '{title}: <span style="color:{color};background-color:{h_color}"' \
                       '>&nbsp;{status} </span>.<BR>'.format(title=_("STATUS"),
                                                             h_color='green',
                                                             color='white',
                                                             status=_("PASSED"))
                txt += '%s<BR>' % _("Violations: There are no violations for the current rule.")
        except KeyError:
            pass

        txt += '<BR><BR>'
    return txt


class RulesUI:

    pluginName = _("Check Rules")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout

        # ## Title
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        self.layout.addWidget(title_label)

        # https://www.w3schools.com/colors/colors_names.asp

        # #############################################################################################################
        # Select All Frame
        # #############################################################################################################
        select_all_label = FCLabel('%s' % _("Select All"), color='CornflowerBlue', bold=True)
        self.layout.addWidget(select_all_label)

        sel_frame = FCFrame()
        self.layout.addWidget(sel_frame)

        sel_grid = GLay(v_spacing=5, h_spacing=3, c_stretch=[1, 0])
        sel_frame.setLayout(sel_grid)

        # Select All Gerber
        gerber_title_lbl = FCLabel('%s:' % _("Gerber"))
        self.all_gerber_obj_cb = FCCheckBox()

        sel_grid.addWidget(gerber_title_lbl, 0, 0)
        sel_grid.addWidget(self.all_gerber_obj_cb, 0, 1)

        # Select All Excellon
        excellon_title_lbl = FCLabel('%s:' % _("Excellon"))
        self.all_exc_obj_cb = FCCheckBox()

        sel_grid.addWidget(excellon_title_lbl, 2, 0)
        sel_grid.addWidget(self.all_exc_obj_cb, 2, 1)

        # Select All Copper Rules
        copper_rules_lbl = FCLabel('%s %s:' % (_("Copper"), _("Rules")))
        self.all_copper_rules_cb = FCCheckBox()

        sel_grid.addWidget(copper_rules_lbl, 4, 0)
        sel_grid.addWidget(self.all_copper_rules_cb, 4, 1)

        # Select All Silk Rules
        silk_rules_lbl = FCLabel('%s %s:' % (_("Silk"), _("Rules")))
        self.all_silk_rules_cb = FCCheckBox()

        sel_grid.addWidget(silk_rules_lbl, 6, 0)
        sel_grid.addWidget(self.all_silk_rules_cb, 6, 1)

        # Select All Soldermask Rules
        solder_rules_lbl = FCLabel('%s %s:' % (_("Soldermask"), _("Rules")))
        self.all_solder_rules_cb = FCCheckBox()

        sel_grid.addWidget(solder_rules_lbl, 8, 0)
        sel_grid.addWidget(self.all_solder_rules_cb, 8, 1)

        # Select All Holes Rules
        holes_rules_lbl = FCLabel('%s %s:' % (_("Holes"), _("Rules")))
        self.all_holes_rules_cb = FCCheckBox()

        sel_grid.addWidget(holes_rules_lbl, 10, 0)
        sel_grid.addWidget(self.all_holes_rules_cb, 10, 1)

        # #############################################################################################################
        # Top Gerber Frame
        # #############################################################################################################
        top_label = FCLabel('%s' % _("Top"), color='red', bold=True)
        self.layout.addWidget(top_label)

        top_frame = FCFrame()
        self.layout.addWidget(top_frame)

        self.top_grid = GLay(v_spacing=5, h_spacing=3, c_stretch=[0, 3, 0])
        top_frame.setLayout(self.top_grid)

        # Copper Top object
        self.copper_t_object = FCComboBox()
        self.copper_t_object.setModel(self.app.collection)
        self.copper_t_object.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.copper_t_object.is_last = True
        self.copper_t_object.obj_type = "Gerber"

        self.copper_t_object_lbl = FCLabel('%s:' % _("Copper"))
        self.copper_t_object_lbl.setToolTip(
            _("The Top Gerber Copper object for which rules are checked.")
        )

        self.copper_t_cb = FCCheckBox()

        self.top_grid.addWidget(self.copper_t_object_lbl, 0, 0)
        self.top_grid.addWidget(self.copper_t_object, 0, 1)
        self.top_grid.addWidget(self.copper_t_cb, 0, 2)

        # SolderMask Top object
        self.sm_t_object = FCComboBox()
        self.sm_t_object.setModel(self.app.collection)
        self.sm_t_object.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.sm_t_object.is_last = True
        self.sm_t_object.obj_type = "Gerber"

        self.sm_t_object_lbl = FCLabel('%s:' % _("SM"))
        self.sm_t_object_lbl.setToolTip(
            _("The Top Gerber Solder Mask object for which rules are checked.")
        )

        self.sm_t_cb = FCCheckBox()

        self.top_grid.addWidget(self.sm_t_object_lbl, 2, 0)
        self.top_grid.addWidget(self.sm_t_object, 2, 1)
        self.top_grid.addWidget(self.sm_t_cb, 2, 2)

        # SilkScreen Top object
        self.ss_t_object = FCComboBox()
        self.ss_t_object.setModel(self.app.collection)
        self.ss_t_object.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.ss_t_object.is_last = True
        self.ss_t_object.obj_type = "Gerber"

        self.ss_t_object_lbl = FCLabel('%s:' % _("Silk"))
        self.ss_t_object_lbl.setToolTip(
            _("The Top Gerber Silkscreen object for which rules are checked.")
        )

        self.ss_t_cb = FCCheckBox()

        self.top_grid.addWidget(self.ss_t_object_lbl, 4, 0)
        self.top_grid.addWidget(self.ss_t_object, 4, 1)
        self.top_grid.addWidget(self.ss_t_cb, 4, 2)

        # #############################################################################################################
        # Bottom Gerber Frame
        # #############################################################################################################
        bottom_label = FCLabel('%s' % _("Bottom"), color='blue', bold=True)
        self.layout.addWidget(bottom_label)

        bottom_frame = FCFrame()
        self.layout.addWidget(bottom_frame)

        self.bottom_grid = GLay(v_spacing=5, h_spacing=3, c_stretch=[0, 3, 0])
        bottom_frame.setLayout(self.bottom_grid)

        # Copper Bottom object
        self.copper_b_object = FCComboBox()
        self.copper_b_object.setModel(self.app.collection)
        self.copper_b_object.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.copper_b_object.is_last = True
        self.copper_b_object.obj_type = "Gerber"

        self.copper_b_object_lbl = FCLabel('%s:' % _("Copper"))
        self.copper_b_object_lbl.setToolTip(
            _("The Bottom Gerber Copper object for which rules are checked.")
        )

        self.copper_b_cb = FCCheckBox()

        self.bottom_grid.addWidget(self.copper_b_object_lbl, 0, 0)
        self.bottom_grid.addWidget(self.copper_b_object, 0, 1)
        self.bottom_grid.addWidget(self.copper_b_cb, 0, 2)

        # SolderMask Bottom object
        self.sm_b_object = FCComboBox()
        self.sm_b_object.setModel(self.app.collection)
        self.sm_b_object.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.sm_b_object.is_last = True
        self.sm_b_object.obj_type = "Gerber"

        self.sm_b_object_lbl = FCLabel('%s:' % _("SM"))
        self.sm_b_object_lbl.setToolTip(
            _("The Bottom Gerber Solder Mask object for which rules are checked.")
        )

        self.sm_b_cb = FCCheckBox()

        self.bottom_grid.addWidget(self.sm_b_object_lbl, 2, 0)
        self.bottom_grid.addWidget(self.sm_b_object, 2, 1)
        self.bottom_grid.addWidget(self.sm_b_cb, 2, 2)

        # SilkScreen Bottom object
        self.ss_b_object = FCComboBox()
        self.ss_b_object.setModel(self.app.collection)
        self.ss_b_object.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.ss_b_object.is_last = True
        self.ss_b_object.obj_type = "Gerber"

        self.ss_b_object_lbl = FCLabel('%s:' % _("Silk"))
        self.ss_b_object_lbl.setToolTip(
            _("The Bottom Gerber Silkscreen object for which rules are checked.")
        )

        self.ss_b_cb = FCCheckBox()

        self.bottom_grid.addWidget(self.ss_b_object_lbl, 4, 0)
        self.bottom_grid.addWidget(self.ss_b_object, 4, 1)
        self.bottom_grid.addWidget(self.ss_b_cb, 4, 2)

        # #############################################################################################################
        # Outline Frame
        # #############################################################################################################
        outline_label = FCLabel('%s' % _("Outline"), color='green', bold=True)
        self.layout.addWidget(outline_label)

        outline_frame = FCFrame()
        self.layout.addWidget(outline_frame)

        self.outline_grid = GLay(v_spacing=5, h_spacing=3, c_stretch=[0, 3, 0])
        outline_frame.setLayout(self.outline_grid)

        self.outline_object = FCComboBox()
        self.outline_object.setModel(self.app.collection)
        self.outline_object.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.outline_object.is_last = True
        self.outline_object.obj_type = "Gerber"

        self.outline_object_lbl = FCLabel('%s:' % _("Outline"))
        self.outline_object_lbl.setToolTip(
            _("The Gerber Outline (Cutout) object for which rules are checked.")
        )

        self.out_cb = FCCheckBox()

        self.outline_grid.addWidget(self.outline_object_lbl, 0, 0)
        self.outline_grid.addWidget(self.outline_object, 0, 1)
        self.outline_grid.addWidget(self.out_cb, 0, 2)

        # #############################################################################################################
        # Excellon Frame
        # #############################################################################################################
        exc_label = FCLabel('%s' % _("Excellon"), color='brown', bold=True)
        exc_label.setToolTip(
            _("Excellon objects for which to check rules.")
        )
        self.layout.addWidget(exc_label)

        exc_frame = FCFrame()
        self.layout.addWidget(exc_frame)

        self.exc_grid = GLay(v_spacing=5, h_spacing=3, c_stretch=[0, 3, 0])
        exc_frame.setLayout(self.exc_grid)

        # Excellon PTH object
        self.e1_object = FCComboBox()
        self.e1_object.setModel(self.app.collection)
        self.e1_object.setRootModelIndex(self.app.collection.index(1, 0, QtCore.QModelIndex()))
        self.e1_object.is_last = True
        self.e1_object.obj_type = "Excellon"

        self.e1_object_lbl = FCLabel('%s:' % "PTH")
        self.e1_object_lbl.setToolTip(
            _("Excellon object for which to check rules.\n"
              "Holds the plated holes or a general Excellon file content.")
        )

        self.e1_cb = FCCheckBox()

        self.exc_grid.addWidget(self.e1_object_lbl, 0, 0)
        self.exc_grid.addWidget(self.e1_object, 0, 1)
        self.exc_grid.addWidget(self.e1_cb, 0, 2)

        # Excellon NPTH object
        self.e2_object = FCComboBox()
        self.e2_object.setModel(self.app.collection)
        self.e2_object.setRootModelIndex(self.app.collection.index(1, 0, QtCore.QModelIndex()))
        self.e2_object.is_last = True
        self.e2_object.obj_type = "Excellon"

        self.e2_object_lbl = FCLabel('%s:' % "NPTH")
        self.e2_object_lbl.setToolTip(
            _("Excellon object for which to check rules.\n"
              "Holds the non-plated holes.")
        )

        self.e2_cb = FCCheckBox()

        self.exc_grid.addWidget(self.e2_object_lbl, 2, 0)
        self.exc_grid.addWidget(self.e2_object, 2, 1)
        self.exc_grid.addWidget(self.e2_cb, 2, 2)

        separator_line = QtWidgets.QFrame()
        separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        self.layout.addWidget(separator_line)

        separator_line = QtWidgets.QFrame()
        separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        self.layout.addWidget(separator_line)

        # #############################################################################################################
        # Rules Frame
        # #############################################################################################################
        rules_copper_label = FCLabel('%s %s' % (_("Copper"), _("Rules")), color='darkorange', bold=True)
        self.layout.addWidget(rules_copper_label)

        copper_frame = FCFrame()
        self.layout.addWidget(copper_frame)

        self.copper_grid = GLay(v_spacing=5, h_spacing=3)
        copper_frame.setLayout(self.copper_grid)

        # Trace size
        self.trace_size_cb = FCCheckBox('%s:' % _("Trace Size"))
        self.trace_size_cb.setToolTip(
            _("This checks if the minimum size for traces is met.")
        )
        self.copper_grid.addWidget(self.trace_size_cb, 0, 0, 1, 2)

        # Trace size value
        self.trace_size_lbl = FCLabel('%s:' % _("Value"))
        self.trace_size_lbl.setToolTip(
            _("Minimum acceptable trace size.")
        )

        self.trace_size_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.trace_size_entry.set_range(0.0000, 10000.0000)
        self.trace_size_entry.set_precision(self.decimals)
        self.trace_size_entry.setSingleStep(0.1)

        self.copper_grid.addWidget(self.trace_size_lbl, 2, 0)
        self.copper_grid.addWidget(self.trace_size_entry, 2, 1)

        self.ts = OptionalInputSection(self.trace_size_cb, [self.trace_size_lbl, self.trace_size_entry])

        # Copper2copper clearance
        self.clearance_copper2copper_cb = FCCheckBox('%s:' % _("Copper to Copper clearance"))
        self.clearance_copper2copper_cb.setToolTip(
            _("This checks if the minimum clearance between copper\n"
              "features is met.")
        )
        self.copper_grid.addWidget(self.clearance_copper2copper_cb, 4, 0, 1, 2)

        # Copper2copper clearance value
        self.clearance_copper2copper_lbl = FCLabel('%s:' % _("Value"))
        self.clearance_copper2copper_lbl.setToolTip(
            _("Minimum acceptable clearance value.")
        )

        self.clearance_copper2copper_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.clearance_copper2copper_entry.set_range(0.0000, 10000.0000)
        self.clearance_copper2copper_entry.set_precision(self.decimals)
        self.clearance_copper2copper_entry.setSingleStep(0.1)

        self.copper_grid.addWidget(self.clearance_copper2copper_lbl, 6, 0)
        self.copper_grid.addWidget(self.clearance_copper2copper_entry, 6, 1)

        self.c2c = OptionalInputSection(
            self.clearance_copper2copper_cb, [self.clearance_copper2copper_lbl, self.clearance_copper2copper_entry])

        # Copper2outline clearance
        self.clearance_copper2ol_cb = FCCheckBox('%s:' % _("Copper to Outline clearance"))
        self.clearance_copper2ol_cb.setToolTip(
            _("This checks if the minimum clearance between copper\n"
              "features and the outline is met.")
        )
        self.copper_grid.addWidget(self.clearance_copper2ol_cb, 8, 0, 1, 2)

        # Copper2outline clearance value
        self.clearance_copper2ol_lbl = FCLabel('%s:' % _("Value"))
        self.clearance_copper2ol_lbl.setToolTip(
            _("Minimum acceptable clearance value.")
        )

        self.clearance_copper2ol_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.clearance_copper2ol_entry.set_range(0.0000, 10000.0000)
        self.clearance_copper2ol_entry.set_precision(self.decimals)
        self.clearance_copper2ol_entry.setSingleStep(0.1)

        self.copper_grid.addWidget(self.clearance_copper2ol_lbl, 10, 0)
        self.copper_grid.addWidget(self.clearance_copper2ol_entry, 10, 1)

        self.c2ol = OptionalInputSection(
            self.clearance_copper2ol_cb, [self.clearance_copper2ol_lbl, self.clearance_copper2ol_entry])

        # Ring integrity check
        self.ring_integrity_cb = FCCheckBox('%s:' % _("Minimum Annular Ring"))
        self.ring_integrity_cb.setToolTip(
            _("This checks if the minimum copper ring left by drilling\n"
              "a hole into a pad is met.")
        )
        self.copper_grid.addWidget(self.ring_integrity_cb, 12, 0, 1, 2)

        # Ring integrity value
        self.ring_integrity_lbl = FCLabel('%s:' % _("Value"))
        self.ring_integrity_lbl.setToolTip(
            _("Minimum acceptable ring value.")
        )

        self.ring_integrity_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.ring_integrity_entry.set_range(0.0000, 10000.0000)
        self.ring_integrity_entry.set_precision(self.decimals)
        self.ring_integrity_entry.setSingleStep(0.1)

        self.copper_grid.addWidget(self.ring_integrity_lbl, 14, 0)
        self.copper_grid.addWidget(self.ring_integrity_entry, 14, 1)

        self.anr = OptionalInputSection(
            self.ring_integrity_cb, [self.ring_integrity_lbl, self.ring_integrity_entry])

        # #############################################################################################################
        # Silk Frame
        # #############################################################################################################
        silk_copper_label = FCLabel('%s %s' % (_("Silk"), _("Rules")), color='teal', bold=True)
        self.layout.addWidget(silk_copper_label)

        silk_frame = FCFrame()
        self.layout.addWidget(silk_frame)

        self.silk_grid = GLay(v_spacing=5, h_spacing=3)
        silk_frame.setLayout(self.silk_grid)

        # "Silkscreen2silkscreen" clearance
        self.clearance_silk2silk_cb = FCCheckBox('%s:' % _("Silk to Silk Clearance"))
        self.clearance_silk2silk_cb.setToolTip(
            _("This checks if the minimum clearance between silkscreen\n"
              "features and silkscreen features is met.")
        )
        self.silk_grid.addWidget(self.clearance_silk2silk_cb, 0, 0, 1, 2)

        # Copper2silkscreen clearance value
        self.clearance_silk2silk_lbl = FCLabel('%s:' % _("Value"))
        self.clearance_silk2silk_lbl.setToolTip(
            _("Minimum acceptable clearance value.")
        )

        self.clearance_silk2silk_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.clearance_silk2silk_entry.set_range(0.0000, 10000.0000)
        self.clearance_silk2silk_entry.set_precision(self.decimals)
        self.clearance_silk2silk_entry.setSingleStep(0.1)

        self.silk_grid.addWidget(self.clearance_silk2silk_lbl, 2, 0)
        self.silk_grid.addWidget(self.clearance_silk2silk_entry, 2, 1)

        self.s2s = OptionalInputSection(
            self.clearance_silk2silk_cb, [self.clearance_silk2silk_lbl, self.clearance_silk2silk_entry])

        # Silkscreen2soldermask clearance
        self.clearance_silk2sm_cb = FCCheckBox('%s:' % _("Silk to Solder Mask Clearance"))
        self.clearance_silk2sm_cb.setToolTip(
            _("This checks if the minimum clearance between silkscreen\n"
              "features and soldermask features is met.")
        )
        self.silk_grid.addWidget(self.clearance_silk2sm_cb, 4, 0, 1, 2)

        # Silkscreen2soldermask clearance value
        self.clearance_silk2sm_lbl = FCLabel('%s:' % _("Value"))
        self.clearance_silk2sm_lbl.setToolTip(
            _("Minimum acceptable clearance value.")
        )

        self.clearance_silk2sm_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.clearance_silk2sm_entry.set_range(0.0000, 10000.0000)
        self.clearance_silk2sm_entry.set_precision(self.decimals)
        self.clearance_silk2sm_entry.setSingleStep(0.1)

        self.silk_grid.addWidget(self.clearance_silk2sm_lbl, 6, 0)
        self.silk_grid.addWidget(self.clearance_silk2sm_entry, 6, 1)

        self.s2sm = OptionalInputSection(
            self.clearance_silk2sm_cb, [self.clearance_silk2sm_lbl, self.clearance_silk2sm_entry])

        # "Silk2outline" clearance
        self.clearance_silk2ol_cb = FCCheckBox('%s:' % _("Silk to Outline Clearance"))
        self.clearance_silk2ol_cb.setToolTip(
            _("This checks if the minimum clearance between silk\n"
              "features and the outline is met.")
        )
        self.silk_grid.addWidget(self.clearance_silk2ol_cb, 8, 0, 1, 2)

        # Silk2outline clearance value
        self.clearance_silk2ol_lbl = FCLabel('%s:' % _("Value"))
        self.clearance_silk2ol_lbl.setToolTip(
            _("Minimum acceptable clearance value.")
        )

        self.clearance_silk2ol_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.clearance_silk2ol_entry.set_range(0.0000, 10000.0000)
        self.clearance_silk2ol_entry.set_precision(self.decimals)
        self.clearance_silk2ol_entry.setSingleStep(0.1)

        self.silk_grid.addWidget(self.clearance_silk2ol_lbl, 10, 0)
        self.silk_grid.addWidget(self.clearance_silk2ol_entry, 10, 1)

        self.s2ol = OptionalInputSection(
            self.clearance_silk2ol_cb, [self.clearance_silk2ol_lbl, self.clearance_silk2ol_entry])

        # #############################################################################################################
        # Soldermask Frame
        # #############################################################################################################
        sm_copper_label = FCLabel('%s %s' % (_("Soldermask"), _("Rules")), color='magenta', bold=True)
        self.layout.addWidget(sm_copper_label)

        solder_frame = FCFrame()
        self.layout.addWidget(solder_frame)

        self.solder_grid = GLay(v_spacing=5, h_spacing=3)
        solder_frame.setLayout(self.solder_grid)

        # Soldermask2soldermask clearance
        self.clearance_sm2sm_cb = FCCheckBox('%s:' % _("Minimum Solder Mask Sliver"))
        self.clearance_sm2sm_cb.setToolTip(
            _("This checks if the minimum clearance between soldermask\n"
              "features and soldermask features is met.")
        )
        self.solder_grid.addWidget(self.clearance_sm2sm_cb, 0, 0, 1, 2)

        # Soldermask2soldermask clearance value

        self.clearance_sm2sm_lbl = FCLabel('%s:' % _("Value"))
        self.clearance_sm2sm_lbl.setToolTip(
            _("Minimum acceptable clearance value.")
        )

        self.clearance_sm2sm_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.clearance_sm2sm_entry.set_range(0.0000, 10000.0000)
        self.clearance_sm2sm_entry.set_precision(self.decimals)
        self.clearance_sm2sm_entry.setSingleStep(0.1)

        self.solder_grid.addWidget(self.clearance_sm2sm_lbl, 2, 0)
        self.solder_grid.addWidget(self.clearance_sm2sm_entry, 2, 1)

        self.sm2sm = OptionalInputSection(
            self.clearance_sm2sm_cb, [self.clearance_sm2sm_lbl, self.clearance_sm2sm_entry])

        # #############################################################################################################
        # Holes Frame
        # #############################################################################################################
        holes_copper_label = FCLabel('%s %s' % (_("Holes"), _("Rules")), color='brown', bold=True)
        self.layout.addWidget(holes_copper_label)

        holes_frame = FCFrame()
        self.layout.addWidget(holes_frame)

        self.holes_grid = GLay(v_spacing=5, h_spacing=3)
        holes_frame.setLayout(self.holes_grid)

        # Hole2Hole clearance
        self.clearance_d2d_cb = FCCheckBox('%s:' % _("Hole to Hole Clearance"))
        self.clearance_d2d_cb.setToolTip(
            _("This checks if the minimum clearance between a drill hole\n"
              "and another drill hole is met.")
        )
        self.holes_grid.addWidget(self.clearance_d2d_cb, 0, 0, 1, 2)

        # Hole2Hole clearance value
        self.clearance_d2d_lbl = FCLabel('%s:' % _("Value"))
        self.clearance_d2d_lbl.setToolTip(
            _("Minimum acceptable clearance value.")
        )

        self.clearance_d2d_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.clearance_d2d_entry.set_range(0.0000, 10000.0000)
        self.clearance_d2d_entry.set_precision(self.decimals)
        self.clearance_d2d_entry.setSingleStep(0.1)

        self.holes_grid.addWidget(self.clearance_d2d_lbl, 2, 0)
        self.holes_grid.addWidget(self.clearance_d2d_entry, 2, 1)

        self.d2d = OptionalInputSection(
            self.clearance_d2d_cb, [self.clearance_d2d_lbl, self.clearance_d2d_entry])

        # Drill holes size check
        self.drill_size_cb = FCCheckBox('%s:' % _("Hole Size"))
        self.drill_size_cb.setToolTip(
            _("This checks if the drill holes\n"
              "sizes are above the threshold.")
        )
        self.holes_grid.addWidget(self.drill_size_cb, 4, 0, 1, 2)

        # Drills holes value
        self.drill_size_lbl = FCLabel('%s:' % _("Value"))
        self.drill_size_lbl.setToolTip(
            _("Minimum acceptable drill size.")
        )

        self.drill_size_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.drill_size_entry.set_range(0.0000, 10000.0000)
        self.drill_size_entry.set_precision(self.decimals)
        self.drill_size_entry.setSingleStep(0.1)

        self.holes_grid.addWidget(self.drill_size_lbl, 6, 0)
        self.holes_grid.addWidget(self.drill_size_entry, 6, 1)

        self.ds = OptionalInputSection(
            self.drill_size_cb, [self.drill_size_lbl, self.drill_size_entry])

        # Buttons
        self.run_button = FCButton(_("Run Rules Check"), bold=True)
        self.run_button.setIcon(QtGui.QIcon(self.app.resource_location + '/rules32.png'))
        self.run_button.setToolTip(
            _("Panelize the specified object around the specified box.\n"
              "In other words it creates multiple copies of the source object,\n"
              "arranged in a 2D array of rows and columns.")
        )
        self.layout.addWidget(self.run_button)

        GLay.set_common_column_size(
            [self.copper_grid, self.solder_grid, self.silk_grid, self.exc_grid, self.top_grid, self.bottom_grid,
             self.outline_grid, self.holes_grid], 0)

        self.layout.addStretch(1)

        # ## Reset Tool
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(
            _("Will reset the tool parameters.")
        )
        self.layout.addWidget(self.reset_button)

        # #############################################################################################################
        # SIGNALS
        # #############################################################################################################
        self.all_gerber_obj_cb.stateChanged.connect(self.on_all_gerber)
        self.all_exc_obj_cb.stateChanged.connect(self.on_all_excellon)
        self.all_copper_rules_cb.stateChanged.connect(self.on_all_copper_rules)
        self.all_silk_rules_cb.stateChanged.connect(self.on_all_silk_rules)
        self.all_solder_rules_cb.stateChanged.connect(self.on_all_solder_rules)
        self.all_holes_rules_cb.stateChanged.connect(self.on_all_holes_rules)

        # #################################### FINSIHED GUI ###########################
        # #############################################################################

    def on_all_gerber(self, state):
        cb_items = [self.top_grid.itemAt(i).widget() for i in range(self.top_grid.count())
                    if isinstance(self.top_grid.itemAt(i).widget(), FCCheckBox)] + \
                   [self.bottom_grid.itemAt(i).widget() for i in range(self.bottom_grid.count())
                    if isinstance(self.bottom_grid.itemAt(i).widget(), FCCheckBox)] + \
                   [self.outline_grid.itemAt(i).widget() for i in range(self.outline_grid.count())
                    if isinstance(self.outline_grid.itemAt(i).widget(), FCCheckBox)]
        for cb in cb_items:
            assert isinstance(cb, FCCheckBox)
            if state:
                cb.setChecked(True)
            else:
                cb.setChecked(False)

    def on_all_excellon(self, state):
        cb_items = [self.exc_grid.itemAt(i).widget() for i in range(self.exc_grid.count())
                    if isinstance(self.exc_grid.itemAt(i).widget(), FCCheckBox)]
        for cb in cb_items:
            assert isinstance(cb, FCCheckBox)
            if state:
                cb.setChecked(True)
            else:
                cb.setChecked(False)

    def on_all_copper_rules(self, state):
        cb_items = [self.copper_grid.itemAt(i).widget() for i in range(self.copper_grid.count())
                    if isinstance(self.copper_grid.itemAt(i).widget(), FCCheckBox)]
        for cb in cb_items:
            assert isinstance(cb, FCCheckBox)
            if state:
                cb.setChecked(True)
            else:
                cb.setChecked(False)

    def on_all_silk_rules(self, state):
        cb_items = [self.silk_grid.itemAt(i).widget() for i in range(self.silk_grid.count())
                    if isinstance(self.silk_grid.itemAt(i).widget(), FCCheckBox)]
        for cb in cb_items:
            assert isinstance(cb, FCCheckBox)
            if state:
                cb.setChecked(True)
            else:
                cb.setChecked(False)

    def on_all_solder_rules(self, state):
        cb_items = [self.solder_grid.itemAt(i).widget() for i in range(self.solder_grid.count())
                    if isinstance(self.solder_grid.itemAt(i).widget(), FCCheckBox)]
        for cb in cb_items:
            assert isinstance(cb, FCCheckBox)
            if state:
                cb.setChecked(True)
            else:
                cb.setChecked(False)

    def on_all_holes_rules(self, state):
        cb_items = [self.holes_grid.itemAt(i).widget() for i in range(self.holes_grid.count())
                    if isinstance(self.holes_grid.itemAt(i).widget(), FCCheckBox)]
        for cb in cb_items:
            assert isinstance(cb, FCCheckBox)
            if state:
                cb.setChecked(True)
            else:
                cb.setChecked(False)

    def confirmation_message(self, accepted, minval, maxval):
        if accepted is False:
            self.app.inform[str, bool].emit('[WARNING_NOTCL] %s: [%.*f, %.*f]' % (_("Edited value is out of range"),
                                                                                  self.decimals,
                                                                                  minval,
                                                                                  self.decimals,
                                                                                  maxval), False)
        else:
            self.app.inform[str, bool].emit('[success] %s' % _("Edited value is within limits."), False)

    def confirmation_message_int(self, accepted, minval, maxval):
        if accepted is False:
            self.app.inform[str, bool].emit('[WARNING_NOTCL] %s: [%d, %d]' %
                                            (_("Edited value is out of range"), minval, maxval), False)
        else:
            self.app.inform[str, bool].emit('[success] %s' % _("Edited value is within limits."), False)
