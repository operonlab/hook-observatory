// Cronicle Admin Page -- Categories

Class.add( Page.Admin, {
	
	gosub_categories: function(args) {
		// show category list
		this.div.removeClass('loading');
		app.setWindowTitle( _t('admin_categories.categories') );
		
		var size = get_inner_window_size();
		var col_width = Math.floor( ((size.width * 0.9) + 200) / 5 );
		
		var html = '';
		
		html += this.getSidebarTabs( 'categories',
			[
				['activity', _t('admin_activity.activity_log')],
				['conf_keys', _t('admin_config_keys.configs')],
				['secrets', _t('admin_secrets.secrets')],
				['api_keys', _t('admin_api_keys.api_keys')],
				['categories', _t('admin_categories.categories')],
				['plugins', _t('admin_plugins.plugins')],
				['servers', _t('admin_servers.servers')],
				['users', _t('admin_users.user_list')]
			]
		);

		var cols = ['Title', 'Description', 'Assigned Events', 'Max Concurrent', 'Actions'];

		html += '<div style="padding:20px 20px 30px 20px">';

		html += '<div class="subtitle">';
			html += _t('admin_categories.categories');
			// html += '<div class="clear"></div>';
		html += '</div>';
		
		// sort by title ascending
		this.categories = app.categories.sort( function(a, b) {
			// return (b.title < a.title) ? 1 : -1;
			return a.title.toLowerCase().localeCompare( b.title.toLowerCase() );
		} );
		
		// render table
		var self = this;
		html += this.getBasicTable( this.categories, cols, 'category', function(cat, idx) {
			var actions = [
				'<span class="link" onMouseUp="$P().edit_category('+idx+')"><b>Edit</b></span>',
				'<span class="link" onMouseUp="$P().delete_category('+idx+')"><b>Delete</b></span>'
			];
			
			var cat_events = find_objects( app.schedule, { category: cat.id } );
			var num_events = cat_events.length;
			
			var tds = [
				'<div class="td_big"><span class="link" onMouseUp="$P().edit_category('+idx+')">' + self.getNiceCategory(cat, col_width) + '</span></div>',
				'<div class="ellip" style="max-width:'+col_width+'px;">' + encode_entities(cat.description || '(No description)') + '</div>',
				num_events ? commify( num_events ) : '(None)',
				cat.max_children ? commify(cat.max_children) : '(No limit)',
				actions.join(' | ')
			];
			
			if (cat && cat.color) {
				if (tds.className) tds.className += ' '; else tds.className = '';
				tds.className += cat.color;
			}
			
			if (!cat.enabled) {
				if (tds.className) tds.className += ' '; else tds.className = '';
				tds.className += 'disabled';
			}
			
			return tds;
		} );
		
		html += '<div style="height:30px;"></div>';
		html += '<center><table><tr>';
			html += '<td><div class="button" style="width:130px;" onMouseUp="$P().edit_category(-1)"><i class="fa fa-plus-circle">&nbsp;&nbsp;</i>' + _t('admin_categories.add_category') + '</div></td>';
		html += '</tr></table></center>';
		
		html += '</div>'; // padding
		html += '</div>'; // sidebar tabs
		
		this.div.html( html );
	},
	
	edit_category: function(idx) {
		// jump to edit sub
		if (idx > -1) Nav.go( '#Admin?sub=edit_category&id=' + this.categories[idx].id );
		else Nav.go( '#Admin?sub=new_category' );
	},
	
	delete_category: function(idx) {
		// delete key from search results
		this.category = this.categories[idx];
		this.show_delete_category_dialog();
	},
	
	gosub_new_category: function(args) {
		// create new Category
		var html = '';
		app.setWindowTitle( _t('admin_categories.new_category') );
		this.div.removeClass('loading');

		html += this.getSidebarTabs( 'new_category',
			[
				['activity', _t('admin_activity.activity_log')],
				['conf_keys', _t('admin_config_keys.configs')],
				['secrets', _t('admin_secrets.secrets')],
				['api_keys', _t('admin_api_keys.api_keys')],
				['categories', _t('admin_categories.categories')],
				['new_category', _t('admin_categories.new_category')],
				['plugins', _t('admin_plugins.plugins')],
				['servers', _t('admin_servers.servers')],
				['users', _t('admin_users.user_list')]
			]
		);

		html += '<div style="padding:20px;"><div class="subtitle">' + _t('admin_categories.add_category') + '</div></div>';
		
		html += '<div style="padding:0px 20px 50px 20px">';
		html += '<center><table style="margin:0;">';
		
		this.category = {
			title: "",
			description: "",
			max_children: 0,
			enabled: 1
		};
		
		html += this.get_category_edit_html();
		
		// buttons at bottom
		html += '<tr><td colspan="2" align="center">';
			html += '<div style="height:30px;"></div>';
			
			html += '<table><tr>';
				html += '<td><div class="button" style="width:120px; font-weight:normal;" onMouseUp="$P().cancel_category_edit()">' + _t('admin_categories.cancel') + '</div></td>';
				html += '<td width="50">&nbsp;</td>';

				html += '<td><div class="button" style="width:120px;" onMouseUp="$P().do_new_category()"><i class="fa fa-plus-circle">&nbsp;&nbsp;</i>' + _t('admin_categories.add_category') + '</div></td>';
			html += '</tr></table>';
			
		html += '</td></tr>';
		
		html += '</table></center>';
		html += '</div>'; // table wrapper div
		
		html += '</div>'; // sidebar tabs
		
		this.div.html( html );
		
		setTimeout( function() {
			$('#fe_ec_title').focus();
		}, 1 );
	},
	
	cancel_category_edit: function() {
		// cancel editing category and return to list
		Nav.go( 'Admin?sub=categories' );
	},
	
	do_new_category: function(force) {
		// create new category
		app.clearError();
		var category = this.get_category_form_json();
		if (!category) return; // error
		
		// pro-tip: embed id in title as bracketed prefix
		if (category.title.match(/^\[(\w+)\]\s*(.+)$/)) {
			category.id = RegExp.$1;
			category.title = RegExp.$2;
		}
		
		this.category = category;
		
		app.showProgress( 1.0, _t('admin_categories.creating_category') );
		app.api.post( 'app/create_category', category, this.new_category_finish.bind(this) );
	},
	
	new_category_finish: function(resp) {
		// new Category created successfully
		app.hideProgress();
		
		// Can't nav to edit_category yet, websocket may not have received update yet
		// Nav.go('Admin?sub=edit_category&id=' + resp.id);
		Nav.go('Admin?sub=categories');
		
		setTimeout( function() {
			app.showMessage('success', _t('admin_categories.the_new_category_was_created_successfull'));
		}, 150 );
	},
	
	gosub_edit_category: function(args) {
		// edit existing Category
		var html = '';
		let category = find_object( app.categories, { id: args.id } );
		if(!category) return app.doError(_t('admin_categories.could_not_locate_category_with_id') + args.id);
		let secret = find_object( app.secrets, { id: args.id } ) || {};

		this.category = deep_copy_object( category )
		
		app.setWindowTitle( _t('admin_categories.editing_category') + category.title + '"' );
		this.div.removeClass('loading');
		
		html += this.getSidebarTabs( 'edit_category',
			[
				['activity', "Activity Log"],
				['conf_keys', "Configs"],
				['secrets', "Secrets"],
				['api_keys', "API Keys"],
				['categories', "Categories"],
				['edit_category', _t('admin_categories.editing_category').replace('\\', '')],
				['plugins', "Plugins"],
				['servers', "Servers"],
				['users', "Users"]
			]
		);

		let secretInfo = secret.size > 0 ? `Edit Secrets (${secret.size})` : 'Attach Secrets'
		
		html += `<div style="padding:20px;"><div class="subtitle">Editing Category &ldquo;${category.title}&rdquo;
		<div class="subtitle_widget"><a href="#Admin?sub=secrets&id=${category.id}" ><b>${secretInfo}</b></a></div>
		</div></div><div style="padding:0px 20px 50px 20px"><center>
		<table style="margin:0;">
		`
		
		html += this.get_category_edit_html();
		
		html += '<tr><td colspan="2" align="center">';
			html += '<div style="height:30px;"></div>';
			
			html += '<table><tr>';
				html += '<td><div class="button" style="width:130px; font-weight:normal;" onMouseUp="$P().cancel_category_edit()">' + _t('admin_categories.cancel') + '</div></td>';
				html += '<td width="50">&nbsp;</td>';
				html += '<td><div class="button" style="width:130px; font-weight:normal;" onMouseUp="$P().show_delete_category_dialog()">' + _t('admin_categories.delete_category') + '</div></td>';
				html += '<td width="50">&nbsp;</td>';
				html += '<td><div class="button" style="width:130px;" onMouseUp="$P().do_save_category()"><i class="fa fa-floppy-o">&nbsp;&nbsp;</i>' + _t('admin_categories.save_changes') + '</div></td>';
			html += '</tr></table>';
			
		html += '</td></tr>';
		
		html += '</table>';
		html += '</center>';
		html += '</div>'; // table wrapper div
		
		html += '</div>'; // sidebar tabs
		
		this.div.html( html );
	},
	
	do_save_category: function() {
		// save changes to category
		app.clearError();
		var category = this.get_category_form_json();
		if (!category) return; // error
		
		this.category = category;
		
		app.showProgress( 1.0, _t('admin_categories.saving_category') );
		app.api.post( 'app/update_category', category, this.save_category_finish.bind(this) );
	},
	
	save_category_finish: function(resp, tx) {
		// new category saved successfully
		var self = this;
		var category = this.category;
		
		app.hideProgress();
		app.showMessage('success', _t('admin_categories.the_category_was_saved_successfully'));
		window.scrollTo( 0, 0 );
		
		// copy active jobs to array
		var jobs = [];
		for (var id in app.activeJobs) {
			var job = app.activeJobs[id];
			if ((job.category == category.id) && !job.detached) jobs.push( job );
		}
		
		// if the cat was disabled and there are running jobs, ask user to abort them
		if (!category.enabled && jobs.length) {
			app.confirm( '<span style="color:red">Abort Jobs</span>', "There " + ((jobs.length != 1) ? 'are' : 'is') + " currently still " + jobs.length + " active " + pluralize('job', jobs.length) + " using the disabled category <b>"+category.title+"</b>.  Do you want to abort " + ((jobs.length != 1) ? 'these' : 'it') + " now?", "Abort", function(result) {
				if (result) {
					app.showProgress( 1.0, _t('admin_categories.aborting') + pluralize('Job', jobs.length) + '...' );
					app.api.post( 'app/abort_jobs', { category: category.id }, function(resp) {
						app.hideProgress();
						if (resp.count > 0) {
							app.showMessage('success', "The " + pluralize('job', resp.count) + " " + ((resp.count != 1) ? 'were' : 'was') + " aborted successfully.");
						}
						else {
							app.showMessage('warning', _t('admin_categories.no_jobs_were_aborted_it_is_likely_they_c'));
						}
					} );
				} // clicked Abort
			} ); // app.confirm
		} // disabled + jobs
	},
	
	show_delete_category_dialog: function() {
		// show dialog confirming category delete action
		var self = this;
		var category = this.category;
		var cat = this.category;
		
		// check for events first
		var cat_events = find_objects( app.schedule, { category: cat.id } );
		var num_events = cat_events.length;
		if (num_events) return app.doError(_t('admin_categories.sorry_you_cannot_delete_a_category_that_'));
		
		// proceed with delete
		var self = this;
		app.confirm( '<span style="color:red">Delete Category</span>', "Are you sure you want to delete the category <b>"+cat.title+"</b>?  There is no way to undo this action.", "Delete", function(result) {
			if (result) {
				app.showProgress( 1.0, _t('admin_categories.deleting_category') );
				app.api.post( 'app/delete_category', cat, self.delete_category_finish.bind(self) );
			}
		} );
	},
	
	delete_category_finish: function(resp, tx) {
		// finished deleting category
		var self = this;
		app.hideProgress();
		
		Nav.go('Admin?sub=categories', 'force');
		
		setTimeout( function() {
			app.showMessage('success', _t('admin_categories.the_category') + "'"+self.category.title+"' was deleted successfully.");
		}, 150 );
	},
	
	get_category_edit_html: function() {
		// get html for editing a category (or creating a new one)
		var html = '';
		var category = this.category;
		var cat = this.category;
		
		// Internal ID
		if (cat.id && this.isAdmin()) {
			html += get_form_table_row( _t('admin_categories.category_id'), '<div style="font-size:14px;">' + cat.id + '</div>' );
			html += get_form_table_caption( _t('admin_categories.the_internal_category_id_used_for_api_ca') );
			html += get_form_table_spacer();
		}
		
		// title
		html += get_form_table_row(_t('admin_categories.category_title'), '<input type="text" id="fe_ec_title" size="25" value="'+escape_text_field_value(cat.title)+'"/>') + 
			get_form_table_caption(_t('admin_categories.enter_a_title_for_the_category_short_and')) + 
			get_form_table_spacer();
		
		// cat enabled
		html += get_form_table_row( _t('admin_categories.active'), '<input type="checkbox" id="fe_ec_enabled" value="1" ' + (cat.enabled ? 'checked="checked"' : '') + '/><label for="fe_ec_enabled">Category Enabled</label>' );
		html += get_form_table_caption( _t('admin_categories.select_whether_events_in_this_category_s') );
		html += get_form_table_spacer();
		
		// description
		html += get_form_table_row(_t('admin_categories.description'), '<textarea id="fe_ec_desc" style="width:500px; height:50px; resize:vertical;">'+escape_text_field_value(cat.description)+'</textarea>') + 
			get_form_table_caption(_t('admin_categories.optionally_enter_a_description_for_the_c')) + 
			get_form_table_spacer();
		
		// max concurrent
		html += get_form_table_row(_t('admin_categories.max_concurrent'), '<select id="fe_ec_max_children">' + render_menu_options([ [0,'No Limit'], 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32 ], cat.max_children, true) + '</select>') + 
			get_form_table_caption(_t('admin_categories.select_the_maximum_number_of_jobs_allowe'));
		html += get_form_table_spacer();
		
		// color
		var current_color = cat.color || 'plain';
		var swatch_html = '';
		var colors = ['plain', 'red', 'green', 'blue', 'skyblue', 'yellow', 'purple', 'orange'];
		for (var idx = 0, len = colors.length; idx < len; idx++) {
			var color = colors[idx];
			swatch_html += '<div class="swatch ' + color + ' ' + ((current_color == color) ? 'active' : '') + '" onMouseUp="$P().select_color(\''+color+'\')"></div>';
		}
		swatch_html += '<div class="clear"></div>';
		
		html += get_form_table_row( _t('admin_categories.highlight_color'), swatch_html );
		html += get_form_table_caption( _t('admin_categories.optionally_select_a_highlight_color_for_') );
		html += get_form_table_spacer();
		
		// default notification options
		var notif_expanded = !!(cat.notify_success || cat.notify_fail || cat.web_hook);
		html += get_form_table_row( _t('admin_categories.notification'), 
			'<div style="font-size:13px;'+(notif_expanded ? 'display:none;' : '')+'"><span class="link addme" onMouseUp="$P().expand_fieldset($(this))"><i class="fa fa-plus-square-o">&nbsp;</i>Default Notification Options</span></div>' + 
			'<fieldset style="padding:10px 10px 0 10px; margin-bottom:5px;'+(notif_expanded ? '' : 'display:none;')+'"><legend class="link addme" onMouseUp="$P().collapse_fieldset($(this))"><i class="fa fa-minus-square-o">&nbsp;</i>Default Notification Options</legend>' + 
				'<div class="plugin_params_label">Default Email on Success:</div>' + 
				'<div class="plugin_params_content"><input type="text" id="fe_ec_notify_success" size="50" value="'+escape_text_field_value(cat.notify_success)+'" placeholder="email@sample.com" spellcheck="false" onChange="$P().update_add_remove_me($(this))"/><span class="link addme" onMouseUp="$P().add_remove_me($(this).prev())"></span></div>' + 
				
				'<div class="plugin_params_label">Default Email on Failure:</div>' + 
				'<div class="plugin_params_content"><input type="text" id="fe_ec_notify_fail" size="50" value="'+escape_text_field_value(cat.notify_fail)+'" placeholder="email@sample.com" spellcheck="false" onChange="$P().update_add_remove_me($(this))"/><span class="link addme" onMouseUp="$P().add_remove_me($(this).prev())"></span></div>' + 
				
				'<div class="plugin_params_label">Default Web Hook URL:</div>' + 
				'<div class="plugin_params_content"><input type="text" id="fe_ec_web_hook" size="60" value="'+escape_text_field_value(cat.web_hook)+'" placeholder="http://" spellcheck="false"/></div>' + 
			'</fieldset>'
		);
		html += get_form_table_caption( _t('admin_categories.optionally_enter_default_email_addresses') );
		html += get_form_table_spacer();
		
		// default resource limits
		var res_expanded = !!(cat.memory_limit || cat.memory_sustain || cat.cpu_limit || cat.cpu_sustain || cat.log_max_size);
		html += get_form_table_row( _t('admin_categories.limits'), 
			'<div style="font-size:13px;'+(res_expanded ? 'display:none;' : '')+'"><span class="link addme" onMouseUp="$P().expand_fieldset($(this))"><i class="fa fa-plus-square-o">&nbsp;</i>Default Resource Limits</span></div>' + 
			'<fieldset style="padding:10px 10px 0 10px; margin-bottom:5px;'+(res_expanded ? '' : 'display:none;')+'"><legend class="link addme" onMouseUp="$P().collapse_fieldset($(this))"><i class="fa fa-minus-square-o">&nbsp;</i>Default Resource Limits</legend>' + 
				
				'<div class="plugin_params_label">Default CPU Limit:</div>' + 
				'<div class="plugin_params_content"><table cellspacing="0" cellpadding="0" class="fieldset_params_table"><tr>' + 
					'<td style="padding-right:2px"><input type="checkbox" id="fe_ec_cpu_enabled" value="1" '+(cat.cpu_limit ? 'checked="checked"' : '')+' /></td>' + 
					'<td><label for="fe_ec_cpu_enabled">Abort job if CPU exceeds</label></td>' + 
					'<td><input type="text" id="fe_ec_cpu_limit" style="width:30px;" value="'+(cat.cpu_limit || 0)+'"/>%</td>' + 
					'<td>for</td>' + 
					'<td>' + this.get_relative_time_combo_box( 'fe_ec_cpu_sustain', cat.cpu_sustain, 'fieldset_params_table' ) + '</td>' + 
				'</tr></table></div>' + 
				
				'<div class="plugin_params_label">Default Memory Limit:</div>' + 
				'<div class="plugin_params_content"><table cellspacing="0" cellpadding="0" class="fieldset_params_table"><tr>' + 
					'<td style="padding-right:2px"><input type="checkbox" id="fe_ec_memory_enabled" value="1" '+(cat.memory_limit ? 'checked="checked"' : '')+' /></td>' + 
					'<td><label for="fe_ec_memory_enabled">Abort job if memory exceeds</label></td>' + 
					'<td>' + this.get_relative_size_combo_box( 'fe_ec_memory_limit', cat.memory_limit, 'fieldset_params_table' ) + '</td>' + 
					'<td>for</td>' + 
					'<td>' + this.get_relative_time_combo_box( 'fe_ec_memory_sustain', cat.memory_sustain, 'fieldset_params_table' ) + '</td>' + 
				'</tr></table></div>' + 
				
				'<div class="plugin_params_label">Default Log Size Limit:</div>' + 
				'<div class="plugin_params_content"><table cellspacing="0" cellpadding="0" class="fieldset_params_table"><tr>' + 
					'<td style="padding-right:2px"><input type="checkbox" id="fe_ec_log_enabled" value="1" '+(cat.log_max_size ? 'checked="checked"' : '')+' /></td>' + 
					'<td><label for="fe_ec_log_enabled">Abort job if log file exceeds</label></td>' + 
					'<td>' + this.get_relative_size_combo_box( 'fe_ec_log_limit', cat.log_max_size, 'fieldset_params_table' ) + '</td>' + 
				'</tr></table></div>' + 
				
			'</fieldset>'
		);
		html += get_form_table_caption( 
			_t('admin_categories.optionally_set_default_cpu_load_memory_u')
		);
		html += get_form_table_spacer();

		html += get_form_table_row(_t('admin_categories.graph'),`<div>
		<input type="color" id="fe_ec_gcolor" name="body"
				value="${category.gcolor || '#3f7ed5'}">
		 <label for="body">Group Color</label>
		 </div>`
		);		
		
		setTimeout( function() {
			$P().update_add_remove_me( $('#fe_ec_notify_success, #fe_ec_notify_fail') );
		}, 1 );
		
		return html;
	},
	
	select_color: function(color) {
		// click on a color swatch
		this.category.color = (color == 'plain') ? '' : color;
		$('.swatch').removeClass('active');
		$('.swatch.'+color).addClass('active');
	},
	
	get_category_form_json: function() {
		// get category elements from form, used for new or edit
		var category = this.category;
		
		category.title = $('#fe_ec_title').val();
		if (!category.title.length) {
			return app.badField('#fe_ec_title', _t('admin_categories.please_enter_a_title_for_the_category'));
		}
		
		category.gcolor = $("#fe_ec_gcolor").val();
		category.enabled = $('#fe_ec_enabled').is(':checked') ? 1 : 0;
		category.description = $('#fe_ec_desc').val();
		category.max_children = parseInt( $('#fe_ec_max_children').val() );
		category.notify_success = $('#fe_ec_notify_success').val();
		category.notify_fail = $('#fe_ec_notify_fail').val();
		category.web_hook = $('#fe_ec_web_hook').val();
		
		// cpu limit
		if ($('#fe_ec_cpu_enabled').is(':checked')) {
			category.cpu_limit = parseInt( $('#fe_ec_cpu_limit').val() );
			if (isNaN(category.cpu_limit)) return app.badField('fe_ec_cpu_limit', _t('admin_categories.please_enter_an_integer_value_for_the_cp'));
			if (category.cpu_limit < 0) return app.badField('fe_ec_cpu_limit', _t('admin_categories.please_enter_a_positive_integer_for_the_'));
			
			category.cpu_sustain = parseInt( $('#fe_ec_cpu_sustain').val() ) * parseInt( $('#fe_ec_cpu_sustain_units').val() );
			if (isNaN(category.cpu_sustain)) return app.badField('fe_ec_cpu_sustain', _t('admin_categories.please_enter_an_integer_value_for_the_lo'));
			if (category.cpu_sustain < 0) return app.badField('fe_ec_cpu_sustain', _t('admin_categories.please_enter_a_positive_integer_for_the_'));
		}
		else {
			category.cpu_limit = 0;
			category.cpu_sustain = 0;
		}
		
		// mem limit
		if ($('#fe_ec_memory_enabled').is(':checked')) {
			category.memory_limit = parseInt( $('#fe_ec_memory_limit').val() ) * parseInt( $('#fe_ec_memory_limit_units').val() );
			if (isNaN(category.memory_limit)) return app.badField('fe_ec_memory_limit', _t('admin_categories.please_enter_an_integer_value_for_the_me'));
			if (category.memory_limit < 0) return app.badField('fe_ec_memory_limit', _t('admin_categories.please_enter_a_positive_integer_for_the_'));
			
			category.memory_sustain = parseInt( $('#fe_ec_memory_sustain').val() ) * parseInt( $('#fe_ec_memory_sustain_units').val() );
			if (isNaN(category.memory_sustain)) return app.badField('fe_ec_memory_sustain', _t('admin_categories.please_enter_an_integer_value_for_the_lo'));
			if (category.memory_sustain < 0) return app.badField('fe_ec_memory_sustain', _t('admin_categories.please_enter_a_positive_integer_for_the_'));
		}
		else {
			category.memory_limit = 0;
			category.memory_sustain = 0;
		}
		
		// job log file size limit
		if ($('#fe_ec_log_enabled').is(':checked')) {
			category.log_max_size = parseInt( $('#fe_ec_log_limit').val() ) * parseInt( $('#fe_ec_log_limit_units').val() );
			if (isNaN(category.log_max_size)) return app.badField('fe_ec_log_limit', _t('admin_categories.please_enter_an_integer_value_for_the_lo'));
			if (category.log_max_size < 0) return app.badField('fe_ec_log_limit', _t('admin_categories.please_enter_a_positive_integer_for_the_'));
		}
		else {
			category.log_max_size = 0;
		}
		
		return category;
	}
	
});