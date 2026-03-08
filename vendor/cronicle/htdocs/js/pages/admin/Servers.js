// Cronicle Admin Page -- Servers

Class.add( Page.Admin, {
	
	gosub_servers: function(args) {
		// show server list, server groups
		this.div.removeClass('loading');
		app.setWindowTitle( _t('admin_servers.servers') );
		
		var size = get_inner_window_size();
		var col_width = Math.floor( ((size.width * 0.9) + 400) / 9 );
		
		var html = '';
		
		html += this.getSidebarTabs( 'servers',
			[
				['activity', _t('admin.activity_log')],
				['conf_keys', _t('admin.config_keys')],
				['secrets', _t('admin.secrets')],
				['api_keys', _t('admin.api_keys')],
				['categories', _t('admin.categories')],
				['plugins', _t('admin.plugins')],
				['servers', _t('admin.servers')],
				['users', _t('admin.users')]
			]
		);
		
		html += '<div style="padding:20px 20px 30px 20px">';
		
		// Active Server Cluster
		
		var cols = ['Hostname', 'IP Address', 'Platform', 'PID', 'Node', 'Engine', 'Groups', 'Status', 'Active Jobs', 'Uptime', 'CPU', 'Mem', 'Actions'];
		
		html += '<div class="subtitle">';
			html += 'Server Cluster';
			// html += '<div class="clear"></div>';
		html += '</div>';
		
		this.servers = [];
		var hostnames = hash_keys_to_array( app.servers ).sort();
		for (var idx = 0, len = hostnames.length; idx < len; idx++) {
			this.servers.push( app.servers[ hostnames[idx] ] );
		}
		
		// include nearby servers under main server list
		if (app.nearby) {
			var hostnames = hash_keys_to_array( app.nearby ).sort();
			for (var idx = 0, len = hostnames.length; idx < len; idx++) {
				var server = app.nearby[ hostnames[idx] ];
				if (!app.servers[server.hostname]) {
					server.nearby = 1;
					this.servers.push( server );
				}
			}
		}
		
		// render table
		var self = this;
		html += this.getBasicTable( this.servers, cols, 'server', function(server, idx) {
			
			// render nearby servers differently
			if (server.nearby) {
				var tds = [
					'<div class="td_big" style="font-weight:normal"><div class="ellip" style="max-width:'+col_width+'px;"><i class="fa fa-eye">&nbsp;</i>' + server.hostname.replace(/\.[\w\-]+\.\w+$/, '') + '</div></div>',
					(server.ip || 'n/a').replace(/^\:\:ffff\:(\d+\.\d+\.\d+\.\d+)$/, '$1'),
					'-', '(Nearby)', '-', '-', '-', '-', '-', '-', '-',
					'<span class="link" onMouseUp="$P().add_server_from_list('+idx+')"><b>Add Server</b></span>'
				];
				tds.className = 'blue';
				return tds;
			} // nearby
			
			var actions = [
				'<span class="link" onMouseUp="$P().restart_server('+idx+')"><b>Restart</b></span>',
				'<span class="link" onMouseUp="$P().shutdown_server('+idx+')"><b>Shutdown</b></span>'
			];
			if (server.disabled) actions = [];
			if (!server.manager) {
				actions.push( '<span class="link" onMouseUp="$P().remove_server('+idx+')"><b>Remove</b></span>' );
			}
			
			var group_names = [];
			var eligible = false;
			for (var idx = 0, len = app.server_groups.length; idx < len; idx++) {
				var group = app.server_groups[idx];
				var regexp = new RegExp( group.regexp, "i" );
				if (server.hostname.match(regexp)) {
					group_names.push( group.title );
					if (group.manager) eligible = true;
				}
			}
			
			var jobs = find_objects( app.activeJobs, { hostname: server.hostname } );
			var num_jobs = jobs.length;
			
			var cpu = 0;
			var mem = 0;
			if (server.data && server.data.cpu) cpu += server.data.cpu;
			if (server.data && server.data.mem) mem += server.data.mem;
			for (idx = 0, len = jobs.length; idx < len; idx++) {
				var job = jobs[idx];
				if (job.cpu && job.cpu.current) cpu += job.cpu.current;
				if (job.mem && job.mem.current) mem += job.mem.current;
			}
			
			var tds = [
				'<div class="td_big">' + self.getNiceGroup(null, server.hostname, col_width) + '</div>',
				(server.ip || 'n/a').replace(/^\:\:ffff\:(\d+\.\d+\.\d+\.\d+)$/, '$1'),
				`<span title="release: ${encode_entities(server.release)}"> ${server.platform}</span>`,
				server.pid,
				server.nodev,
				server.engine || '',
				group_names.length ? group_names.join(', ') : '(None)',
				server.manager ? '<span class="color_label green"><i class="fa fa-check">&nbsp;</i>Manager</span>' : (eligible ? '<span class="color_label purple">Backup</span>' : '<span class="color_label blue">Worker</span>'),
				num_jobs ? commify( num_jobs ) : '(None)',
				get_text_from_seconds( server.uptime, true, true ).replace(/\bday\b/, 'days'),
				short_float(cpu) + '%',
				get_text_from_bytes(mem),
				actions.join(' | ')
			];
			
			if (server.disabled) tds.className = 'disabled';
			
			return tds;
		} );
		
		html += '<div style="height:25px;"></div>';
		html += '<center><table><tr>';
			html += '<td><div class="button" style="width:130px;" onMouseUp="$P().add_server()"><i class="fa fa-plus-circle">&nbsp;&nbsp;</i>' + _t('admin_servers.add_server') + '</div></td>';
		html += '</tr></table></center>';
		
		html += '<div style="height:30px;"></div>';
		
		// Server Groups
		
		var col_width = Math.floor( ((size.width * 0.9) + 300) / 6 );
		
		var cols = ['Title', 'Hostname Match', '# of Servers', '# of Events', 'Class', 'Actions'];
		
		html += '<div class="subtitle">';
			html += 'Server Groups';
			// html += '<div class="clear"></div>';
		html += '</div>';
		
		// sort by title ascending
		this.server_groups = app.server_groups.sort( function(a, b) {
			// return (b.title < a.title) ? 1 : -1;
			return a.title.toLowerCase().localeCompare( b.title.toLowerCase() );
		} );
		
		// render table
		var self = this;
		html += this.getBasicTable( this.server_groups, cols, 'group', function(group, idx) {
			var actions = [
				'<span class="link" onMouseUp="$P().edit_group('+idx+')"><b>Edit</b></span>',
				'<span class="link" onMouseUp="$P().delete_group('+idx+')"><b>Delete</b></span>'
			];
			
			var regexp = new RegExp( group.regexp, "i" );
			var num_servers = 0;
			for (var hostname in app.servers) {
				if (hostname.match(regexp)) num_servers++;
			}
			
			var group_events = find_objects( app.schedule, { target: group.id } );
			var num_events = group_events.length;
			
			return [
				'<div class="td_big" style="white-space:nowrap;"><span class="link" onMouseUp="$P().edit_group('+idx+')">' + self.getNiceGroup(group, null, col_width) + '</span></div>',
				'<div class="ellip" style="font-family:monospace; max-width:'+col_width+'px;">/' + encode_entities(group.regexp) + '/</div>',
				// group.description || '(No description)',
				num_servers ? commify( num_servers) : '(None)',
				num_events ? commify( num_events ) : '(None)',
				group.manager ? '<b>Manager Eligible</b>' : 'Worker Only',
				actions.join(' | ')
			];
		} );
		
		html += '<div style="height:25px;"></div>';
		html += '<center><table><tr>';
			html += '<td><div class="button" style="width:130px;" onMouseUp="$P().edit_group(-1)"><i class="fa fa-plus-circle">&nbsp;&nbsp;</i>' + _t('admin_servers.add_group') + '</div></td>';
		html += '</tr></table></center>';
		
		html += '</div>'; // padding
		html += '</div>'; // sidebar tabs
		
		this.div.html( html );
	},
	
	add_server_from_list: function(idx) {
		// add a server right away, from the nearby list
		var server = this.servers[idx];
		
		app.showProgress( 1.0, _t('admin_servers.adding_server') );
		app.api.post( 'app/add_server', { hostname: server.ip || server.hostname }, function(resp) {
			app.hideProgress();
			app.showMessage('success', _t('admin_servers.server_was_added_successfully'));
			// self['gosub_servers'](self.args);
		} ); // api.post
	},
	
	add_server: function() {
		// show dialog allowing user to enter an arbitrary hostname to add
		var html = '';
		
		// html += '<div style="font-size:12px; color:#777; margin-bottom:15px;">Typically, servers should automatically add themselves to the cluster, if they are within UDP broadcast range (i.e. on the same LAN).  You should only need to manually add a server in special circumstances, e.g. if it is remotely hosted in another datacenter or network.</div>';
		
		// html += '<div style="font-size:12px; color:#777; margin-bottom:20px;">Note that the new server cannot already be a manager server, nor part of another '+app.name+' server cluster, and the current manager server must be able to reach it.</div>';
		
		html += '<center><table>' +
			// get_form_table_spacer() +
			get_form_table_row(_t('admin_servers.hostname_or_ip'), '<input type="text" id="fe_as_hostname" style="width:280px" value="" spellcheck="false"/>') +
			get_form_table_caption(_t('admin_servers.enter_the_hostname_or_ip_of_the_server_y')) +
		'</table></center>';
		
		app.confirm( '<i class="mdi mdi-desktop-tower mdi-lg">&nbsp;&nbsp;</i>Add Server', html, "Add Server", function(result) {
			app.clearError();
			
			if (result) {
				var hostname = $('#fe_as_hostname').val().toLowerCase();
				if (!hostname) return app.badField('fe_as_hostname', _t('admin_servers.please_enter_a_server_hostname_or_ip_add'));
				if (!hostname.match(/^[\w\-\.]+$/)) return app.badField('fe_as_hostname', _t('admin_servers.please_enter_a_valid_server_hostname_or_'));
				if (app.servers[hostname]) return app.badField('fe_as_hostname', _t('admin_servers.that_server_is_already_in_the_cluster'));
				Dialog.hide();
				
				app.showProgress( 1.0, _t('admin_servers.adding_server') );
				app.api.post( 'app/add_server', { hostname: hostname }, function(resp) {
					app.hideProgress();
					app.showMessage('success', _t('admin_servers.server_was_added_successfully'));
					// self['gosub_servers'](self.args);
				} ); // api.post
			} // user clicked add
		} ); // app.confirm
		
		setTimeout( function() { 
			$('#fe_as_hostname').focus();
		}, 1 );
	},
	
	remove_server: function(idx) {
		// remove manual server after user confirmation
		var server = this.servers[idx];
		
		var jobs = find_objects( app.activeJobs, { hostname: server.hostname } );
		if (jobs.length) return app.doError(_t('admin_servers.sorry_you_cannot_remove_a_server_that_ha'));
		
		// proceed with remove
		var self = this;
		app.confirm( '<span style="color:red">Remove Server</span>', "Are you sure you want to remove the server <b>"+server.hostname+"</b>?", "Remove", function(result) {
			if (result) {
				app.showProgress( 1.0, _t('admin_servers.removing_server') );
				app.api.post( 'app/remove_server', server, function(resp) {
					app.hideProgress();
					app.showMessage('success', _t('admin_servers.server_was_removed_successfully'));
					// self.gosub_servers(self.args);
				} );
			}
		} );
	},
	
	edit_group: function(idx) {
		// edit group (-1 == new group)
		var self = this;
		var group = (idx > -1) ? this.server_groups[idx] : {
			title: "",
			regexp: "",
			manager: 0
		};
		var edit = (idx > -1) ? true : false;
		var html = '';
		
		html += '<table>';
		
		// Internal ID
		if (edit && this.isAdmin()) {
			html += get_form_table_row( _t('admin_servers.group_id'), '<div style="font-size:14px;">' + group.id + '</div>' );
			html += get_form_table_caption( _t('admin_servers.the_internal_group_id_used_for_api_calls') );
			html += get_form_table_spacer();
		}
		
		html += 
			get_form_table_row(_t('admin_servers.group_title'), '<input type="text" id="fe_eg_title" size="25" value="'+escape_text_field_value(group.title)+'"/>') + 
			get_form_table_caption(_t('admin_servers.enter_a_title_for_the_server_group_short')) + 
			get_form_table_spacer() + 
			get_form_table_row(_t('admin_servers.hostname_match'), '<input type="text" id="fe_eg_regexp" size="30" style="font-family:monospace; font-size:13px;" value="'+escape_text_field_value(group.regexp)+'" spellcheck="false"/>') + 
			get_form_table_caption(_t('admin_servers.enter_a_regular_expression_to_autoassign')) + 
			get_form_table_spacer() + 
			get_form_table_row(_t('admin_servers.server_class'), '<select id="fe_eg_manager">' + render_menu_options([ [1,'manager Eligible'], [0,'worker Only'] ], group.manager, false) + '</select>') + 
			get_form_table_caption(_t('admin_servers.select_whether_servers_in_the_group_are_')) + 
		'</table>';
		
		app.confirm( '<i class="mdi mdi-server-network">&nbsp;&nbsp;</i>' + (edit ? "Edit Server Group" : "Add Server Group"), html, edit ? "Save Changes" : "Add Group", function(result) {
			app.clearError();
			
			if (result) {
				group.title = $('#fe_eg_title').val();
				if (!group.title) return app.badField('fe_eg_title', _t('admin_servers.please_enter_a_title_for_the_server_grou'));
				group.regexp = $('#fe_eg_regexp').val().replace(/^\/(.+)\/$/, '$1');
				if (!group.regexp) return app.badField('fe_eg_regexp', _t('admin_servers.please_enter_a_regular_expression_for_th'));
				
				try { new RegExp(group.regexp); }
				catch(err) {
					return app.badField('fe_eg_regexp', _t('admin_servers.invalid_regular_expression') + err);
				}
				
				group.manager = parseInt( $('#fe_eg_manager').val() );
				Dialog.hide();
				
				// pro-tip: embed id in title as bracketed prefix
				if (!edit && group.title.match(/^\[(\w+)\]\s*(.+)$/)) {
					group.id = RegExp.$1;
					group.title = RegExp.$2;
				}
				
				app.showProgress( 1.0, edit ? "Saving group..." : "Adding group..." );
				app.api.post( edit ? 'app/update_server_group' : 'app/create_server_group', group, function(resp) {
					app.hideProgress();
					app.showMessage('success', _t('admin_servers.server_group_was') + (edit ? "saved" : "added") + " successfully.");
					// self['gosub_servers'](self.args);
				} ); // api.post
			} // user clicked add
		} ); // app.confirm
		
		setTimeout( function() { 
			if (!$('#fe_eg_title').val()) $('#fe_eg_title').focus();
		}, 1 );
	},
	
	delete_group: function(idx) {
		// delete selected server group
		var group = this.server_groups[idx];
		
		// make sure user isn't deleting final manager group
		if (group.manager) {
			var num_managers = 0;
			for (var idx = 0, len = this.server_groups.length; idx < len; idx++) {
				if (this.server_groups[idx].manager) num_managers++;
			}
			if (num_managers == 1) {
				return app.doError(_t('admin_servers.sorry_you_cannot_delete_the_last_manager'));
			}
		}
		
		// check for events first
		var group_events = find_objects( app.schedule, { target: group.id } );
		var num_events = group_events.length;
		if (num_events) return app.doError(_t('admin_servers.sorry_you_cannot_delete_a_group_that_has'));
		
		// proceed with delete
		var self = this;
		app.confirm( '<span style="color:red">Delete Server Group</span>', "Are you sure you want to delete the server group <b>"+group.title+"</b>?  There is no way to undo this action.", "Delete", function(result) {
			if (result) {
				app.showProgress( 1.0, _t('admin_servers.deleting_group') );
				app.api.post( 'app/delete_server_group', group, function(resp) {
					app.hideProgress();
					app.showMessage('success', _t('admin_servers.server_group_was_deleted_successfully'));
					// self.gosub_servers(self.args);
				} );
			}
		} );
	},
	
	restart_server: function(idx) {
		// restart server after confirmation
		var self = this;
		var server = this.servers[idx];
		
		app.confirm( '<span style="color:red">Restart Server</span>', "Are you sure you want to restart the server <b>"+server.hostname+"</b>?  All server jobs will be aborted.", "Restart", function(result) {
			if (result) {
				app.showProgress( 1.0, _t('admin_servers.restarting_server') );
				app.api.post( 'app/restart_server', server, function(resp) {
					app.hideProgress();
					app.showMessage('success', _t('admin_servers.server_is_being_restarted_in_the_backgro'));
					// self.gosub_servers(self.args);
				} );
			}
		} );
	},
	
	shutdown_server: function(idx) {
		// shutdown server after confirmation
		var self = this;
		var server = this.servers[idx];
		
		app.confirm( '<span style="color:red">Shutdown Server</span>', "Are you sure you want to shutdown the server <b>"+server.hostname+"</b>?  All server jobs will be aborted.", "Shutdown", function(result) {
			if (result) {
				app.showProgress( 1.0, _t('admin_servers.shutting_down_server') );
				app.api.post( 'app/shutdown_server', server, function(resp) {
					app.hideProgress();
					app.showMessage('success', _t('admin_servers.server_is_being_shut_down_in_the_backgro'));
					// self.gosub_servers(self.args);
				} );
			}
		} );
	}
	
});